from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import OpsTask
from .task_resolution_engine import ACTIVE_STATUSES, _classify_blocker, _fallback_plan

router = APIRouter(prefix="/self-healing", tags=["self healing"])

HEALABLE = {
    "transient_provider_error",
    "provider_configuration",
    "evidence_gap",
    "data_conflict",
    "unclassified",
}


def _linked_lead_ids(db: Session, organization_id: int):
    return select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )


def _diagnose(task: OpsTask) -> dict[str, Any]:
    blocker = _classify_blocker(task)
    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "blocker": blocker,
        "healability": "automatic_candidate" if blocker in HEALABLE else "guarded",
        "fallback_plan": _fallback_plan(task, blocker),
        "error": task.error,
    }


def _heal_metadata(task: OpsTask, diagnosis: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": "self_healing_engine",
        "diagnosis": diagnosis,
        "healing_policy": {
            "safe_retry": diagnosis["blocker"] == "transient_provider_error",
            "alternate_authorized_source": diagnosis["blocker"] in {"provider_configuration", "evidence_gap", "data_conflict"},
            "human_gate_required": diagnosis["blocker"] == "compliance_or_approval",
            "access_control_bypass_allowed": False,
            "fabricated_success_allowed": False,
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    linked = _linked_lead_ids(db, principal.organization_id)
    rows = db.scalars(select(OpsTask).where(
        OpsTask.lead_id.in_(linked),
        OpsTask.status.in_(ACTIVE_STATUSES),
    ).order_by(OpsTask.priority.desc(), OpsTask.updated_at.asc()).limit(100)).all()
    diagnoses = [_diagnose(row) for row in rows]
    counts: dict[str, int] = {}
    for item in diagnoses:
        counts[item["blocker"]] = counts.get(item["blocker"], 0) + 1
    return {
        "active_tasks": len(rows),
        "blockers": counts,
        "diagnoses": diagnoses,
        "policy": "Heal operational failures automatically only through authorized, reversible paths; never bypass compliance or evidence gates.",
    }


@router.post("/scan")
def scan(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    limit = max(1, min(100, int((payload or {}).get("limit") or 25)))
    linked = _linked_lead_ids(db, principal.organization_id)
    rows = db.scalars(select(OpsTask).where(
        OpsTask.lead_id.in_(linked),
        OpsTask.status.in_(ACTIVE_STATUSES),
    ).order_by(OpsTask.priority.desc(), OpsTask.updated_at.asc()).limit(limit)).all()
    results = []
    for task in rows:
        diagnosis = _diagnose(task)
        result = dict(task.result or {})
        result["self_healing"] = _heal_metadata(task, diagnosis)
        task.result = result
        # Never auto-complete here. Healing prepares or updates the recovery path;
        # task_resolution_engine owns execution/proof-of-success.
        if diagnosis["blocker"] == "transient_provider_error" and task.status == "blocked":
            task.status = "pending"
            task.error = "Self-healing marked task retryable through the authorized resolver path"
        task.updated_at = datetime.now(timezone.utc)
        results.append({"task_id": task.id, "status": task.status, "diagnosis": diagnosis})
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="self_healing_scan",
        summary=f"Self-healing evaluated {len(results)} active tasks",
        metadata_json={"evaluated": len(results)},
    ))
    db.commit()
    return {"evaluated": len(results), "results": results}

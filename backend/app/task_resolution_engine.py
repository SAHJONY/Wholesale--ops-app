from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .acquisition_worker import _process_one
from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead, OpsTask

router = APIRouter(prefix="/task-resolution", tags=["task resolution"])

ACTIVE_STATUSES = {"queued", "pending", "in_progress", "blocked"}


def _linked(db: Session, organization_id: int, entity_type: str, entity_id: int | None) -> bool:
    if not entity_id:
        return False
    return db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
        WorkspaceEntity.entity_id == entity_id,
    )) is not None


def _assert_task_access(db: Session, principal: Principal, task: OpsTask) -> None:
    if task.lead_id and _linked(db, principal.organization_id, "lead", task.lead_id):
        return
    if task.buyer_id and _linked(db, principal.organization_id, "buyer", task.buyer_id):
        return
    raise HTTPException(404, "Task not found in this workspace")


def _classify_blocker(task: OpsTask) -> str:
    text = " ".join([
        str(task.error or ""),
        str(task.payload or {}),
        str(task.result or {}),
    ]).lower()
    if any(token in text for token in ("api key", "configuration", "not configured", "credential", "provider")):
        return "provider_configuration"
    if any(token in text for token in ("owner", "county", "deed", "record", "parcel", "assessor")):
        return "evidence_gap"
    if any(token in text for token in ("compliance", "dnc", "tcpa", "consent", "approval", "authority")):
        return "compliance_or_approval"
    if any(token in text for token in ("timeout", "429", "rate limit", "temporar", "retry")):
        return "transient_provider_error"
    if any(token in text for token in ("conflict", "ambiguous", "mismatch")):
        return "data_conflict"
    return "unclassified"


def _fallback_plan(task: OpsTask, blocker: str) -> list[dict[str, Any]]:
    base = [
        {"strategy": "preserve_evidence", "action": "Never fabricate a successful result; retain source provenance and blocker details."},
    ]
    if blocker == "provider_configuration":
        return base + [
            {"strategy": "authorized_provider", "action": "Use any configured licensed provider already available to the Wholesale OS."},
            {"strategy": "official_public_source", "action": "Fall back to assessor, recorder, tax, sheriff, or government open-data evidence where applicable."},
            {"strategy": "manual_assisted", "action": "Prepare the exact lookup packet for a human-assisted public-source check when automation is not authorized."},
        ]
    if blocker == "evidence_gap":
        return base + [
            {"strategy": "alternate_official_source", "action": "Try a second authoritative county or government source."},
            {"strategy": "address_seed", "action": "Use the verified property address/APN as the lookup seed when owner-of-record is unavailable."},
            {"strategy": "cross_verify", "action": "Require independent corroboration before promoting identity/contact facts."},
        ]
    if blocker == "compliance_or_approval":
        return base + [
            {"strategy": "human_gate", "action": "Keep the task blocked until the required human/compliance approval is recorded."},
            {"strategy": "non_contact_progress", "action": "Continue title, condition, underwriting, buyer research, and other non-outreach work in parallel."},
        ]
    if blocker == "transient_provider_error":
        return base + [
            {"strategy": "safe_retry", "action": "Retry through the authorized provider path without bypassing access controls."},
            {"strategy": "provider_fallback", "action": "Switch to another authorized source if the preferred provider remains unavailable."},
        ]
    if blocker == "data_conflict":
        return base + [
            {"strategy": "independent_source", "action": "Resolve conflicts with a second independent authoritative source."},
            {"strategy": "fail_closed", "action": "Do not promote the disputed fact until the conflict is resolved."},
        ]
    return base + [
        {"strategy": "diagnostic_review", "action": "Inspect task payload/result/error and route to the closest existing worker or owner review queue."},
    ]


def _proof(task: OpsTask, execution: dict[str, Any] | None = None) -> dict[str, Any]:
    execution = execution or {}
    completed = False
    evidence: list[str] = []

    if task.task_type == "owner_resolution":
        result = execution.get("result") or {}
        attom = result.get("attom") or {}
        batchdata = result.get("batchdata") or {}
        county_case_id = result.get("county_case_id")
        if attom.get("status") == "completed":
            evidence.append("property_provider_evidence")
        if batchdata.get("status") == "completed":
            evidence.append("contact_provider_evidence")
        if county_case_id:
            evidence.append("county_verification_case_created")
        completed = bool(county_case_id and (attom.get("status") == "completed" or batchdata.get("status") == "completed"))
        return {
            "success": completed,
            "evidence": evidence,
            "success_definition": "provider evidence acquired and county verification case created",
            "note": "Owner/contact facts remain unverified until the downstream evidence gates pass.",
        }

    if task.status == "completed" and task.result:
        return {"success": True, "evidence": ["task_marked_completed_with_result"], "success_definition": "task has persisted result evidence"}

    return {"success": False, "evidence": evidence, "success_definition": "task-specific proof-of-success not yet satisfied"}


async def _execute_known_task(db: Session, principal: Principal, task: OpsTask) -> dict[str, Any]:
    if task.task_type == "owner_resolution":
        if not task.lead_id:
            return {"status": "blocked", "error": "owner_resolution task is missing lead_id"}
        lead = db.get(Lead, task.lead_id)
        if not lead:
            return {"status": "blocked", "error": "lead not found"}
        return await _process_one(db, principal, lead, force=True)
    return {"status": "no_automatic_executor", "task_type": task.task_type}


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    linked_leads = select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )
    rows = db.scalars(select(OpsTask).where(
        OpsTask.lead_id.in_(linked_leads),
        OpsTask.status.in_(ACTIVE_STATUSES),
    ).order_by(OpsTask.priority.desc(), OpsTask.updated_at.asc()).limit(100)).all()
    counts = dict(db.execute(select(OpsTask.status, func.count(OpsTask.id)).where(
        OpsTask.lead_id.in_(linked_leads),
    ).group_by(OpsTask.status)).all())
    return {
        "counts": counts,
        "active": [{
            "id": row.id,
            "task_type": row.task_type,
            "status": row.status,
            "priority": row.priority,
            "lead_id": row.lead_id,
            "buyer_id": row.buyer_id,
            "blocker": _classify_blocker(row),
            "fallback_plan": _fallback_plan(row, _classify_blocker(row)),
            "error": row.error,
        } for row in rows],
        "completion_policy": "A task is completed only when its task-specific proof-of-success predicate is satisfied.",
    }


@router.post("/tasks/{task_id}/resolve")
async def resolve_task(task_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    task = db.get(OpsTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    _assert_task_access(db, principal, task)

    blocker = _classify_blocker(task)
    task.status = "in_progress"
    task.error = None
    task.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        execution = await _execute_known_task(db, principal, task)
    except Exception as exc:
        db.rollback()
        task = db.get(OpsTask, task_id)
        task.status = "blocked"
        task.error = f"{type(exc).__name__}: {exc}"
        task.result = {
            "resolver": "task_resolution_engine",
            "blocker": _classify_blocker(task),
            "fallback_plan": _fallback_plan(task, _classify_blocker(task)),
        }
        task.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {"task_id": task.id, "status": task.status, "error": task.error, "result": task.result}

    task = db.get(OpsTask, task_id)
    proof = _proof(task, execution)
    task.result = {
        "resolver": "task_resolution_engine",
        "execution": execution,
        "proof": proof,
        "blocker": blocker,
        "fallback_plan": _fallback_plan(task, blocker),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    task.status = "completed" if proof.get("success") else "blocked"
    if not proof.get("success"):
        task.error = "Proof-of-success not yet satisfied; follow fallback plan"
    task.updated_at = datetime.now(timezone.utc)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=task.lead_id,
        activity_type="task_resolution_attempted",
        summary=f"Task {task.id} resolution finished with status {task.status}",
        metadata_json={"task_id": task.id, "task_type": task.task_type, "proof": proof, "blocker": blocker},
    ))
    db.commit()
    return {"task_id": task.id, "status": task.status, "proof": proof, "execution": execution, "fallback_plan": task.result.get("fallback_plan")}


@router.post("/run-pending")
async def run_pending(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    limit = max(1, min(25, int((payload or {}).get("limit") or 10)))
    linked_leads = select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )
    rows = db.scalars(select(OpsTask).where(
        OpsTask.lead_id.in_(linked_leads),
        OpsTask.status.in_(ACTIVE_STATUSES),
    ).order_by(OpsTask.priority.desc(), OpsTask.updated_at.asc()).limit(limit)).all()
    results = []
    for row in rows:
        if row.task_type != "owner_resolution":
            results.append({
                "task_id": row.id,
                "status": row.status,
                "blocker": _classify_blocker(row),
                "fallback_plan": _fallback_plan(row, _classify_blocker(row)),
                "automatic_executor": False,
            })
            continue
        results.append(await resolve_task(row.id, principal, db))
    return {"processed": len(results), "results": results}

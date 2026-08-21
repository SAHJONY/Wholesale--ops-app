from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Deal, Lead, OpsTask

router = APIRouter(prefix="/self-improvement", tags=["self improvement"])

SAFE_AUTO_CHANGES = {
    "reprioritize_tasks",
    "increase_verification_priority",
    "preserve_successful_fallback",
}


def _linked_lead_ids(db: Session, organization_id: int):
    return select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )


def _metrics(db: Session, organization_id: int) -> dict[str, Any]:
    linked = _linked_lead_ids(db, organization_id)
    task_rows = db.execute(select(OpsTask.status, func.count(OpsTask.id)).where(
        OpsTask.lead_id.in_(linked),
    ).group_by(OpsTask.status)).all()
    task_counts = {str(status): int(count) for status, count in task_rows}
    lead_rows = db.execute(select(Lead.status, func.count(Lead.id)).where(
        Lead.id.in_(linked),
    ).group_by(Lead.status)).all()
    lead_counts = {str(status): int(count) for status, count in lead_rows}
    deal_rows = db.execute(select(Deal.stage, func.count(Deal.id)).where(
        Deal.property_id.in_(select(WorkspaceEntity.entity_id).where(
            WorkspaceEntity.organization_id == organization_id,
            WorkspaceEntity.entity_type == "property",
        )),
    ).group_by(Deal.stage)).all()
    deal_counts = {str(stage): int(count) for stage, count in deal_rows}
    resolution_attempts = db.scalar(select(func.count(CrmActivity.id)).where(
        CrmActivity.organization_id == organization_id,
        CrmActivity.activity_type == "task_resolution_attempted",
    )) or 0
    return {
        "tasks": task_counts,
        "leads": lead_counts,
        "deals": deal_counts,
        "resolution_attempts": int(resolution_attempts),
    }


def _recommend(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = metrics.get("tasks") or {}
    leads = metrics.get("leads") or {}
    recommendations: list[dict[str, Any]] = []
    blocked = int(tasks.get("blocked") or 0)
    pending = int(tasks.get("pending") or 0) + int(tasks.get("queued") or 0)
    verification = int(leads.get("verification") or 0)

    if blocked:
        recommendations.append({
            "id": "reduce_blocked_tasks",
            "change": "increase_verification_priority",
            "expected_effect": "Move evidence-gap tasks into resolution earlier.",
            "risk": "low",
            "auto_apply_allowed": True,
            "success_metric": "blocked task count decreases without increasing false completions",
        })
    if pending:
        recommendations.append({
            "id": "oldest_high_priority_first",
            "change": "reprioritize_tasks",
            "expected_effect": "Reduce queue age by processing high-priority old tasks first.",
            "risk": "low",
            "auto_apply_allowed": True,
            "success_metric": "pending queue age and count decrease",
        })
    if verification:
        recommendations.append({
            "id": "reuse_verified_resolution_paths",
            "change": "preserve_successful_fallback",
            "expected_effect": "Reuse successful source cascades by blocker type without weakening evidence thresholds.",
            "risk": "low",
            "auto_apply_allowed": True,
            "success_metric": "verification throughput improves with unchanged confidence requirements",
        })

    recommendations.append({
        "id": "high_impact_changes_need_review",
        "change": "approval_required",
        "expected_effect": "Keep pricing rules, compliance thresholds, outreach permissions, contracts, payments, provider credentials, and production code changes under explicit review.",
        "risk": "guardrail",
        "auto_apply_allowed": False,
        "success_metric": "no unauthorized consequential changes",
    })
    return recommendations


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    metrics = _metrics(db, principal.organization_id)
    return {
        "metrics": metrics,
        "recommendations": _recommend(metrics),
        "policy": "Learn from persisted outcomes; auto-apply only low-risk reversible operational changes. High-impact changes require approval and validation.",
    }


@router.post("/cycle")
def cycle(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    apply_safe = bool((payload or {}).get("apply_safe", True))
    metrics = _metrics(db, principal.organization_id)
    recommendations = _recommend(metrics)
    applied: list[dict[str, Any]] = []

    if apply_safe:
        linked = _linked_lead_ids(db, principal.organization_id)
        # Reversible operational improvement: evidence/verification tasks receive
        # priority floor 85. No pricing, compliance, contact authorization, or
        # completion status is changed by this engine.
        rows = db.scalars(select(OpsTask).where(
            OpsTask.lead_id.in_(linked),
            OpsTask.status.in_(["queued", "pending", "in_progress", "blocked"]),
        )).all()
        for task in rows:
            text = f"{task.task_type} {task.error or ''} {task.payload or {}}".lower()
            if any(token in text for token in ("verify", "owner", "county", "title", "condition", "resolution")) and task.priority < 85:
                old = task.priority
                task.priority = 85
                task.updated_at = datetime.now(timezone.utc)
                applied.append({"task_id": task.id, "change": "priority_floor", "from": old, "to": 85})

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="self_improvement_cycle",
        summary=f"Self-improvement evaluated operating metrics and applied {len(applied)} safe changes",
        metadata_json={
            "before_metrics": metrics,
            "recommendations": recommendations,
            "applied": applied,
            "guardrails": {
                "pricing_rules_changed": False,
                "compliance_thresholds_changed": False,
                "outreach_authorization_changed": False,
                "contracts_or_payments_changed": False,
            },
        },
    ))
    db.commit()
    return {"metrics": metrics, "recommendations": recommendations, "applied": applied}

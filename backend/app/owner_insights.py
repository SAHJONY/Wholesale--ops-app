from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .database import get_db
from .models import Approval, Deal, Lead, OpsTask, Property
from .percentages import canonical_percentage

router = APIRouter(prefix="/owner-insights", tags=["owner attention center"])


def _ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _rows(db: Session, model, ids: list[int]):
    return db.scalars(select(model).where(model.id.in_(ids))).all() if ids else []


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sort_time(value: datetime | None) -> datetime:
    return _as_utc(value) or datetime.min.replace(tzinfo=timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _follow_up_buckets(
    follow_ups: list[FollowUpTask],
    now: datetime,
) -> tuple[list[FollowUpTask], list[FollowUpTask]]:
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    due_soon_cutoff = now_utc + timedelta(hours=24)
    overdue = []
    due_soon = []
    for item in follow_ups:
        due_at = _as_utc(item.due_at)
        if item.status != "open" or due_at is None:
            continue
        if due_at < now_utc:
            overdue.append(item)
        elif due_at <= due_soon_cutoff:
            due_soon.append(item)
    return overdue, due_soon


@router.get("/summary")
def summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    organization_id = principal.organization_id
    now = datetime.now(timezone.utc)

    lead_ids = _ids(db, organization_id, "lead")
    deal_ids = _ids(db, organization_id, "deal")
    task_ids = _ids(db, organization_id, "task")
    approval_ids = _ids(db, organization_id, "approval")

    leads = _rows(db, Lead, lead_ids)
    deals = _rows(db, Deal, deal_ids)
    tasks = _rows(db, OpsTask, task_ids)
    approvals = _rows(db, Approval, approval_ids)

    follow_ups = db.scalars(select(FollowUpTask).where(
        FollowUpTask.organization_id == organization_id,
    ).order_by(FollowUpTask.priority.desc(), FollowUpTask.due_at.asc())).all()

    activities = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == organization_id,
    ).order_by(CrmActivity.created_at.desc()).limit(50)).all()

    property_ids = [deal.property_id for deal in deals]
    properties = _rows(db, Property, property_ids)
    property_by_id = {item.id: item for item in properties}

    overdue, due_soon = _follow_up_buckets(follow_ups, now)
    failed = [item for item in tasks if item.status == "failed"]
    queued = [item for item in tasks if item.status == "queued"]
    pending = [item for item in approvals if item.status == "pending"]
    high_risk = [item for item in deals if item.stage not in {"closed", "dead"} and (item.risk_score or 0) >= 60]

    attention_score = min(
        100,
        len(overdue) * 15 + len(failed) * 20 + len(pending) * 10 + len(high_risk) * 8 + len(due_soon) * 4,
    )
    status = "critical" if attention_score >= 60 else "watch" if attention_score >= 25 else "stable"

    return {
        "generated_at": now.isoformat(),
        "organization": {"id": organization_id, "name": principal.organization_name},
        "status": status,
        "attention_score": attention_score,
        "counts": {
            "overdue_followups": len(overdue),
            "due_soon_followups": len(due_soon),
            "failed_tasks": len(failed),
            "queued_tasks": len(queued),
            "pending_approvals": len(pending),
            "high_risk_deals": len(high_risk),
            "total_leads": len(leads),
            "active_deals": len([item for item in deals if item.stage not in {"closed", "dead"}]),
        },
        "overdue_followups": [{
            "id": item.id,
            "title": item.title,
            "priority": item.priority,
            "lead_id": item.lead_id,
            "deal_id": item.deal_id,
            "due_at": _iso_utc(item.due_at),
        } for item in overdue[:25]],
        "due_soon_followups": [{
            "id": item.id,
            "title": item.title,
            "priority": item.priority,
            "lead_id": item.lead_id,
            "deal_id": item.deal_id,
            "due_at": _iso_utc(item.due_at),
        } for item in due_soon[:25]],
        "failed_tasks": [{
            "id": item.id,
            "task_type": item.task_type,
            "priority": item.priority,
            "lead_id": item.lead_id,
            "error": item.error,
            "updated_at": _iso_utc(item.updated_at),
        } for item in sorted(
            failed,
            key=lambda item: _sort_time(item.updated_at or item.created_at),
            reverse=True,
        )[:25]],
        "pending_approvals": [{
            "id": item.id,
            "action_type": item.action_type,
            "summary": item.summary,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "created_at": _iso_utc(item.created_at),
        } for item in sorted(pending, key=lambda item: _sort_time(item.created_at), reverse=True)[:25]],
        "high_risk_deals": [{
            "id": item.id,
            "stage": item.stage,
            "risk_score": item.risk_score,
            "probability_to_close": canonical_percentage(item.probability_to_close),
            "projected_assignment_fee": item.projected_assignment_fee or 0,
            "next_action": item.next_action,
            "property": {
                "city": property_by_id.get(item.property_id).city if property_by_id.get(item.property_id) else None,
                "state": property_by_id.get(item.property_id).state if property_by_id.get(item.property_id) else None,
                "zip_code": property_by_id.get(item.property_id).zip_code if property_by_id.get(item.property_id) else None,
            },
        } for item in sorted(high_risk, key=lambda x: x.risk_score or 0, reverse=True)[:25]],
        "recent_activity": [{
            "id": item.id,
            "type": item.activity_type,
            "summary": item.summary,
            "lead_id": item.lead_id,
            "deal_id": item.deal_id,
            "created_at": _iso_utc(item.created_at),
        } for item in activities[:30]],
    }

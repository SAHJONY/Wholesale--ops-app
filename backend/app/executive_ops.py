from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .autonomy import AUTONOMY_AGENTS, create_task, execute_next_tasks, run_agent
from .database import get_db
from .models import AgentRun, Approval, Buyer, Deal, Lead, OpsTask, Property
from .percentages import canonical_percentage
from .services import lead_score

router = APIRouter(prefix="/executive", tags=["executive operations"])


def _ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _rows(db: Session, model, ids: list[int]):
    return db.scalars(select(model).where(model.id.in_(ids))).all() if ids else []


def _priority(score: float, timeline_days: int | None) -> int:
    urgency = 15 if timeline_days is not None and timeline_days <= 14 else 0
    return int(max(1, min(100, round(score + urgency))))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sort_time(value: datetime | None) -> datetime:
    return _as_utc(value) or datetime.min.replace(tzinfo=timezone.utc)


def _agent_health(runs: list[AgentRun], now: datetime) -> list[dict]:
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    latest_by_agent: dict[str, AgentRun] = {}
    for run in sorted(runs, key=lambda item: _sort_time(item.created_at), reverse=True):
        latest_by_agent.setdefault(run.agent_name, run)

    health = []
    for definition in AUTONOMY_AGENTS:
        run = latest_by_agent.get(definition["name"])
        created_at = _as_utc(run.created_at) if run else None
        stale = created_at is None or created_at < now_utc - timedelta(hours=24)
        health.append({
            **definition,
            "health": "idle" if not run else "stale" if stale else "healthy",
            "last_run_at": created_at.isoformat() if created_at else None,
            "last_status": run.status if run else None,
            "confidence": run.confidence if run else None,
        })
    return health


def _weighted_revenue(deals: list[Deal]) -> float:
    return sum(
        (deal.projected_assignment_fee or 0)
        * canonical_percentage(deal.probability_to_close)
        / 100
        for deal in deals
    )


@router.get("/command-center")
def command_center(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    organization_id = principal.organization_id
    lead_ids = _ids(db, organization_id, "lead")
    deal_ids = _ids(db, organization_id, "deal")
    buyer_ids = _ids(db, organization_id, "buyer")
    task_ids = _ids(db, organization_id, "task")
    approval_ids = _ids(db, organization_id, "approval")
    run_ids = _ids(db, organization_id, "agent_run")

    leads = _rows(db, Lead, lead_ids)
    deals = _rows(db, Deal, deal_ids)
    buyers = _rows(db, Buyer, buyer_ids)
    tasks = _rows(db, OpsTask, task_ids)
    approvals = _rows(db, Approval, approval_ids)
    runs = _rows(db, AgentRun, run_ids)

    property_ids = [deal.property_id for deal in deals]
    properties = _rows(db, Property, property_ids)
    property_by_id = {item.id: item for item in properties}

    ranked_leads = []
    for lead in leads:
        score = lead_score(
            float(lead.motivation_score or 0),
            float(lead.equity_score or 0),
            float(lead.distress_score or 0),
        )
        ranked_leads.append({
            "lead_id": lead.id,
            "seller_name": lead.seller_name,
            "status": lead.status,
            "source": lead.source,
            "score": score,
            "priority": _priority(score, lead.timeline_days),
            "timeline_days": lead.timeline_days,
        })
    ranked_leads.sort(key=lambda item: (item["priority"], item["score"]), reverse=True)

    active_deals = [deal for deal in deals if deal.stage not in {"closed", "dead"}]
    deal_risk = []
    for deal in active_deals:
        prop = property_by_id.get(deal.property_id)
        deal_risk.append({
            "deal_id": deal.id,
            "stage": deal.stage,
            "risk_score": float(deal.risk_score or 0),
            "probability_to_close": canonical_percentage(deal.probability_to_close),
            "projected_assignment_fee": deal.projected_assignment_fee or 0,
            "next_action": deal.next_action,
            "property": {
                "city": prop.city if prop else None,
                "state": prop.state if prop else None,
                "zip_code": prop.zip_code if prop else None,
            },
        })
    deal_risk.sort(key=lambda item: float(item["risk_score"] or 0), reverse=True)

    now = datetime.now(timezone.utc)
    agent_health = _agent_health(runs, now)

    queued = [task for task in tasks if task.status == "queued"]
    failed = [task for task in tasks if task.status == "failed"]
    pending = [approval for approval in approvals if approval.status == "pending"]
    projected_revenue = sum(deal.projected_assignment_fee or 0 for deal in active_deals)
    weighted_revenue = _weighted_revenue(active_deals)

    return {
        "generated_at": now.isoformat(),
        "organization": {"id": organization_id, "name": principal.organization_name},
        "mode": "supervised_autonomous",
        "kpis": {
            "total_leads": len(leads),
            "hot_leads": len([item for item in ranked_leads if item["score"] >= 70]),
            "active_deals": len(active_deals),
            "qualified_buyers": len(buyers),
            "projected_assignment_revenue": projected_revenue,
            "probability_weighted_revenue": round(weighted_revenue, 2),
            "queued_tasks": len(queued),
            "failed_tasks": len(failed),
            "pending_approvals": len(pending),
        },
        "priority_leads": ranked_leads[:15],
        "deal_risk": deal_risk[:15],
        "agent_health": agent_health,
        "queue": [{
            "id": task.id,
            "task_type": task.task_type,
            "priority": int(task.priority or 0),
            "status": task.status,
            "lead_id": task.lead_id,
            "created_at": _sort_time(task.created_at).isoformat(),
        } for task in sorted(queued, key=lambda item: (-(item.priority or 0), _sort_time(item.created_at)))[:25]],
        "approvals": [{
            "id": approval.id,
            "action_type": approval.action_type,
            "summary": approval.summary,
            "entity_type": approval.entity_type,
            "entity_id": approval.entity_id,
            "created_at": _sort_time(approval.created_at).isoformat(),
        } for approval in sorted(pending, key=lambda item: _sort_time(item.created_at), reverse=True)[:25]],
    }


@router.post("/run-cycle")
def run_cycle(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    payload = payload or {}
    execute_limit = max(1, min(int(payload.get("execute_limit", 25)), 50))
    organization_id = principal.organization_id

    run = run_agent(
        db,
        "executive-orchestrator",
        "Scan tenant pipeline, prioritize qualified seller opportunities, and dispatch safe work",
        {"organization_id": organization_id, "trigger": "owner_command_center"},
    )

    completed = execute_next_tasks(db, limit=execute_limit, organization_id=organization_id)
    second_pass = execute_next_tasks(db, limit=execute_limit, organization_id=organization_id)
    all_completed = completed + second_pass

    summary = {
        "agent_run_id": run.id,
        "executed": len(all_completed),
        "completed": len([task for task in all_completed if task.status == "completed"]),
        "failed": len([task for task in all_completed if task.status == "failed"]),
        "follow_on_queued": len(_ids(db, organization_id, "task")),
    }
    db.add(CrmActivity(
        organization_id=organization_id,
        user_id=principal.user_id,
        activity_type="executive_cycle",
        summary=f"Executive autonomous cycle executed {summary['executed']} tasks",
        metadata_json=summary,
    ))
    db.commit()

    return {
        **summary,
        "mode": "supervised_autonomous",
        "tasks": [{
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "result": task.result,
            "error": task.error,
        } for task in all_completed],
    }

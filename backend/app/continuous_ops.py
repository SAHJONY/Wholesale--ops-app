import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import AppUser, CrmActivity, FollowUpTask, Membership, Organization, WorkspaceEntity
from .autonomy import AUTONOMY_AGENTS, execute_next_tasks, run_agent
from .database import get_db
from .market_selection import DEFAULT_WEIGHTS, _collect, _composite, _confidence, _score_market
from .models import Lead
from .services import lead_score

router = APIRouter(prefix="/scheduled", tags=["scheduled autonomous operations"])


def _link(db: Session, organization_id: int, entity_type: str, entity_id: int) -> None:
    exists = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
        WorkspaceEntity.entity_id == entity_id,
    ))
    if not exists:
        db.add(WorkspaceEntity(
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
        ))
        db.flush()


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _authorized_cron(authorization: str | None) -> None:
    configured = os.getenv("CRON_SECRET")
    if not configured:
        raise HTTPException(503, "CRON_SECRET is not configured")
    expected = f"Bearer {configured}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Invalid cron authorization")


def _market_intelligence_snapshot(db: Session, organization_id: int, *, limit: int = 25) -> dict:
    markets = _collect(db, organization_id)
    ranked: list[dict] = []
    confidence_order = {"none": 0, "low": 1, "moderate": 2, "high": 3}

    for entry in markets.values():
        scored = _score_market(entry)
        composite, coverage = _composite(scored["scores"], DEFAULT_WEIGHTS)
        if composite is None:
            continue
        confidence = _confidence(coverage)
        ranked.append({
            "zip_code": entry["zip_code"],
            "states": sorted(entry["states"]),
            "cities": sorted(city for city in entry["cities"] if city),
            "counties": sorted(county for county in entry["counties"] if county),
            "composite_score": composite,
            "evidence_coverage_percent": coverage,
            "confidence": confidence,
            "cash_buyers": len(entry["buyers"]),
            "properties": len(entry["properties"]),
            "distress_facts": entry["distress_facts"],
            "scores": scored["scores"],
            "missing_dimensions": [
                key for key, present in scored["evidence"].items() if not present
            ],
        })

    ranked.sort(
        key=lambda row: (
            confidence_order[row["confidence"]],
            row["composite_score"],
            row["evidence_coverage_percent"],
            row["cash_buyers"],
        ),
        reverse=True,
    )
    top = ranked[:max(1, min(limit, 100))]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "nationwide_workspace",
        "ranking_model": "buyer_first_zip_market_selection",
        "markets_considered": len(markets),
        "markets_ranked": len(ranked),
        "high_confidence_markets": sum(1 for row in ranked if row["confidence"] == "high"),
        "top_markets": top,
        "weights": DEFAULT_WEIGHTS,
        "boundary": (
            "This snapshot ranks only SAHJONY workspace evidence. External national benchmark rankings "
            "remain a separate evidence layer and are not inferred from missing internal data."
        ),
    }


def _run_workspace_cycle(db: Session, organization: Organization, trigger: str = "vercel_cron") -> dict:
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == organization.id,
        Membership.role == "owner",
    ))
    owner = db.get(AppUser, membership.user_id) if membership else None
    if not membership or not owner or not owner.is_active:
        return {"organization_id": organization.id, "status": "skipped", "reason": "active owner not found"}

    lead_ids = _linked_ids(db, organization.id, "lead")
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all() if lead_ids else []

    followups_created = 0
    now = datetime.now(timezone.utc)
    for lead in leads:
        score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
        if score < 45 or lead.status in {"closed", "dead"}:
            continue
        existing = db.scalar(select(FollowUpTask.id).where(
            FollowUpTask.organization_id == organization.id,
            FollowUpTask.lead_id == lead.id,
            FollowUpTask.status == "open",
        ))
        if not existing:
            db.add(FollowUpTask(
                organization_id=organization.id,
                lead_id=lead.id,
                assigned_user_id=owner.id,
                title=f"Autonomous follow-up: {lead.seller_name}",
                priority=int(min(100, max(45, score))),
                due_at=now + timedelta(hours=4 if score >= 70 else 24),
                notes="Created by the scheduled supervised-autonomous cycle.",
            ))
            followups_created += 1

    runs = []
    for definition in AUTONOMY_AGENTS:
        run = run_agent(
            db,
            definition["name"],
            f"Scheduled tenant cycle: {definition['role']}",
            {"organization_id": organization.id, "trigger": trigger},
        )
        _link(db, organization.id, "agent_run", run.id)
        task_id = run.output_json.get("task_id") if isinstance(run.output_json, dict) else None
        if task_id:
            _link(db, organization.id, "task", int(task_id))
        runs.append(run)

    first_pass = execute_next_tasks(db, limit=25, organization_id=organization.id)
    second_pass = execute_next_tasks(db, limit=25, organization_id=organization.id)
    completed = first_pass + second_pass
    market_snapshot = _market_intelligence_snapshot(db, organization.id)

    db.add(CrmActivity(
        organization_id=organization.id,
        user_id=owner.id,
        activity_type="daily_market_intelligence",
        summary=(
            f"Daily market intelligence ranked {market_snapshot['markets_ranked']} workspace markets; "
            f"{market_snapshot['high_confidence_markets']} high-confidence"
        ),
        metadata_json=market_snapshot,
    ))

    summary = {
        "organization_id": organization.id,
        "organization": organization.name,
        "status": "completed",
        "trigger": trigger,
        "agents_run": len(runs),
        "tasks_executed": len(completed),
        "tasks_completed": len([item for item in completed if item.status == "completed"]),
        "tasks_failed": len([item for item in completed if item.status == "failed"]),
        "followups_created": followups_created,
        "market_intelligence": {
            "markets_considered": market_snapshot["markets_considered"],
            "markets_ranked": market_snapshot["markets_ranked"],
            "high_confidence_markets": market_snapshot["high_confidence_markets"],
            "top_markets": market_snapshot["top_markets"][:5],
        },
    }
    db.add(CrmActivity(
        organization_id=organization.id,
        user_id=owner.id,
        activity_type="scheduled_cycle",
        summary=f"Scheduled autonomous cycle executed {summary['tasks_executed']} tasks",
        metadata_json=summary,
    ))
    db.commit()
    return summary


@router.get("/operations")
def scheduled_operations(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _authorized_cron(authorization)
    organizations = db.scalars(select(Organization).where(Organization.is_active.is_(True))).all()
    results = [_run_workspace_cycle(db, organization, "vercel_cron") for organization in organizations]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "supervised_autonomous",
        "organizations_processed": len(results),
        "results": results,
    }


@router.post("/run-now")
def run_now(
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, principal.organization_id)
    if not organization or not organization.is_active:
        raise HTTPException(404, "Active organization not found")
    return _run_workspace_cycle(db, organization, "owner_manual_schedule")


@router.get("/status")
def scheduled_status(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    latest = db.scalar(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.activity_type == "scheduled_cycle",
    ).order_by(CrmActivity.created_at.desc()))
    return {
        "mode": "supervised_autonomous",
        "schedule": "0 13 * * *",
        "schedule_label": "Daily at 8:00 AM Central during daylight saving time",
        "cron_secret_configured": bool(os.getenv("CRON_SECRET")),
        "last_run": None if not latest else {
            "id": latest.id,
            "summary": latest.summary,
            "metadata": latest.metadata_json,
            "created_at": latest.created_at,
        },
    }


@router.get("/market-intelligence")
def scheduled_market_intelligence(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    latest = db.scalar(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.activity_type == "daily_market_intelligence",
    ).order_by(CrmActivity.created_at.desc()))
    if latest:
        return {
            "persisted": True,
            "activity_id": latest.id,
            "created_at": latest.created_at,
            **(latest.metadata_json or {}),
        }
    return {
        "persisted": False,
        **_market_intelligence_snapshot(db, principal.organization_id),
    }


@router.get("/history")
def scheduled_history(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    items = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.activity_type == "scheduled_cycle",
    ).order_by(CrmActivity.created_at.desc()).limit(50)).all()
    return [{
        "id": item.id,
        "summary": item.summary,
        "metadata": item.metadata_json,
        "created_at": item.created_at,
    } for item in items]

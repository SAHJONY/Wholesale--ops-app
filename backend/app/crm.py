from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .autonomy import create_task
from .database import get_db
from .models import Deal, Lead, Property
from .operating_system import create_or_update_deal
from .schemas import LeadCreate
from .services import calculate_mao, distress_score, lead_score

router = APIRouter(prefix="/crm", tags=["crm"])

PIPELINE_STAGES = [
    "new",
    "contacting",
    "qualified",
    "offer_prepared",
    "offer_sent",
    "negotiating",
    "under_contract",
    "disposition",
    "closing",
    "closed",
    "nurture",
    "dead",
]


def _workspace_link(db: Session, organization_id: int, entity_type: str, entity_id: int) -> WorkspaceEntity:
    existing = db.scalar(select(WorkspaceEntity).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
        WorkspaceEntity.entity_id == entity_id,
    ))
    if existing:
        return existing
    link = WorkspaceEntity(organization_id=organization_id, entity_type=entity_type, entity_id=entity_id)
    db.add(link)
    db.flush()
    return link


def _assert_linked(db: Session, principal: Principal, entity_type: str, entity_id: int) -> None:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == entity_type,
        WorkspaceEntity.entity_id == entity_id,
    ))
    if not linked:
        raise HTTPException(404, f"{entity_type.title()} not found in this workspace")


def _activity(db: Session, principal: Principal, activity_type: str, summary: str,
              lead_id: int | None = None, deal_id: int | None = None, metadata: dict | None = None) -> CrmActivity:
    item = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        deal_id=deal_id,
        activity_type=activity_type,
        summary=summary,
        metadata_json=metadata or {},
    )
    db.add(item)
    return item


@router.get("/pipeline")
def pipeline(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    deal_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
    )).all()
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all() if lead_ids else []
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all() if deal_ids else []
    counts = {stage: 0 for stage in PIPELINE_STAGES}
    for lead in leads:
        counts[lead.status if lead.status in counts else "new"] += 1
    for deal in deals:
        stage = deal.stage if deal.stage in counts else "qualified"
        counts[stage] += 1
    projected_revenue = sum(deal.projected_assignment_fee or 0 for deal in deals if deal.stage not in {"closed", "dead"})
    return {
        "organization_id": principal.organization_id,
        "stages": [{"stage": stage, "count": counts[stage]} for stage in PIPELINE_STAGES],
        "total_leads": len(leads),
        "active_deals": len([deal for deal in deals if deal.stage not in {"closed", "dead"}]),
        "projected_assignment_revenue": projected_revenue,
    }


@router.post("/leads")
def create_workspace_lead(
    payload: LeadCreate,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    p = payload.property
    score = distress_score(p.distress_signals)
    mao = calculate_mao(p.arv, p.repairs) if p.arv is not None and p.repairs is not None else None
    lead = Lead(
        seller_name=payload.seller_name,
        phone=payload.phone,
        email=payload.email,
        source=payload.source,
        motivation_score=payload.motivation_score,
        equity_score=payload.equity_score,
        distress_score=score,
        timeline_days=payload.timeline_days,
        notes=payload.notes,
    )
    lead.property = Property(**p.model_dump(), mao=mao)
    db.add(lead)
    db.flush()
    _workspace_link(db, principal.organization_id, "lead", lead.id)
    task = create_task(db, "score_lead", {"trigger": "crm_lead_created", "organization_id": principal.organization_id},
                       priority=80, lead_id=lead.id)
    _activity(db, principal, "lead_created", f"Lead created for {lead.seller_name}", lead_id=lead.id,
              metadata={"source": lead.source, "property_id": lead.property.id})
    db.commit()
    return {
        "id": lead.id,
        "property_id": lead.property.id,
        "status": lead.status,
        "distress_score": score,
        "lead_score": lead_score(lead.motivation_score, lead.equity_score, score),
        "mao": mao,
        "autonomy_task_id": task.id,
    }


@router.get("/leads")
def list_workspace_leads(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    leads = db.scalars(select(Lead).where(Lead.id.in_(ids)).order_by(Lead.created_at.desc())).all() if ids else []
    return [{
        "id": lead.id,
        "property_id": lead.property.id if lead.property else None,
        "seller_name": lead.seller_name,
        "phone": lead.phone,
        "email": lead.email,
        "status": lead.status,
        "source": lead.source,
        "motivation_score": lead.motivation_score,
        "equity_score": lead.equity_score,
        "distress_score": lead.distress_score,
        "address": lead.property.address if lead.property else None,
        "city": lead.property.city if lead.property else None,
        "state": lead.property.state if lead.property else None,
        "zip_code": lead.property.zip_code if lead.property else None,
        "mao": lead.property.mao if lead.property else None,
        "created_at": lead.created_at,
    } for lead in leads]


@router.patch("/leads/{lead_id}/stage")
def update_lead_stage(
    lead_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    _assert_linked(db, principal, "lead", lead_id)
    stage = str(payload.get("stage") or "").strip()
    if stage not in PIPELINE_STAGES:
        raise HTTPException(422, "Invalid pipeline stage")
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    previous = lead.status
    lead.status = stage
    _activity(db, principal, "stage_changed", f"Lead moved from {previous} to {stage}", lead_id=lead.id,
              metadata={"previous": previous, "stage": stage})
    db.commit()
    return {"id": lead.id, "status": lead.status}


@router.post("/leads/{lead_id}/deal")
def convert_lead_to_deal(
    lead_id: int,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead or not lead.property:
        raise HTTPException(404, "Lead property not found")
    deal = create_or_update_deal(db, lead.property.id)
    _workspace_link(db, principal.organization_id, "deal", deal.id)
    lead.status = "qualified"
    _activity(db, principal, "deal_created", f"Deal #{deal.id} created", lead_id=lead.id, deal_id=deal.id,
              metadata={"property_id": deal.property_id})
    db.commit()
    return {"deal_id": deal.id, "lead_id": lead.id, "stage": deal.stage,
            "projected_assignment_fee": deal.projected_assignment_fee}


@router.get("/activities")
def list_activities(
    lead_id: int | None = None,
    deal_id: int | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    query = select(CrmActivity).where(CrmActivity.organization_id == principal.organization_id)
    if lead_id is not None:
        _assert_linked(db, principal, "lead", lead_id)
        query = query.where(CrmActivity.lead_id == lead_id)
    if deal_id is not None:
        _assert_linked(db, principal, "deal", deal_id)
        query = query.where(CrmActivity.deal_id == deal_id)
    items = db.scalars(query.order_by(CrmActivity.created_at.desc()).limit(200)).all()
    return [{
        "id": item.id,
        "type": item.activity_type,
        "summary": item.summary,
        "lead_id": item.lead_id,
        "deal_id": item.deal_id,
        "user_id": item.user_id,
        "metadata": item.metadata_json,
        "created_at": item.created_at,
    } for item in items]


@router.post("/activities")
def create_activity(
    payload: dict,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    lead_id = payload.get("lead_id")
    deal_id = payload.get("deal_id")
    if lead_id is not None:
        _assert_linked(db, principal, "lead", int(lead_id))
    if deal_id is not None:
        _assert_linked(db, principal, "deal", int(deal_id))
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise HTTPException(422, "summary is required")
    item = _activity(db, principal, str(payload.get("activity_type") or "note"), summary,
                     lead_id=int(lead_id) if lead_id is not None else None,
                     deal_id=int(deal_id) if deal_id is not None else None,
                     metadata=payload.get("metadata") or {})
    db.commit()
    return {"id": item.id, "created": True}


@router.get("/follow-ups")
def list_follow_ups(
    status: str | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    query = select(FollowUpTask).where(FollowUpTask.organization_id == principal.organization_id)
    if status:
        query = query.where(FollowUpTask.status == status)
    items = db.scalars(query.order_by(FollowUpTask.priority.desc(), FollowUpTask.due_at.asc()).limit(250)).all()
    return [{
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "priority": item.priority,
        "lead_id": item.lead_id,
        "deal_id": item.deal_id,
        "assigned_user_id": item.assigned_user_id,
        "due_at": item.due_at,
        "notes": item.notes,
    } for item in items]


@router.post("/follow-ups")
def create_follow_up(
    payload: dict,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    lead_id = payload.get("lead_id")
    deal_id = payload.get("deal_id")
    if lead_id is not None:
        _assert_linked(db, principal, "lead", int(lead_id))
    if deal_id is not None:
        _assert_linked(db, principal, "deal", int(deal_id))
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(422, "title is required")
    due_at = datetime.fromisoformat(payload["due_at"]) if payload.get("due_at") else None
    item = FollowUpTask(
        organization_id=principal.organization_id,
        lead_id=int(lead_id) if lead_id is not None else None,
        deal_id=int(deal_id) if deal_id is not None else None,
        assigned_user_id=payload.get("assigned_user_id") or principal.user_id,
        title=title,
        priority=max(1, min(int(payload.get("priority") or 50), 100)),
        due_at=due_at,
        notes=payload.get("notes"),
    )
    db.add(item)
    _activity(db, principal, "follow_up_created", title, lead_id=item.lead_id, deal_id=item.deal_id,
              metadata={"priority": item.priority, "due_at": payload.get("due_at")})
    db.commit()
    return {"id": item.id, "status": item.status}


@router.patch("/follow-ups/{task_id}")
def update_follow_up(
    task_id: int,
    payload: dict,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    item = db.get(FollowUpTask, task_id)
    if not item or item.organization_id != principal.organization_id:
        raise HTTPException(404, "Follow-up not found")
    if "status" in payload:
        status = str(payload["status"])
        if status not in {"open", "in_progress", "completed", "cancelled"}:
            raise HTTPException(422, "Invalid status")
        item.status = status
        item.completed_at = datetime.utcnow() if status == "completed" else None
    if "title" in payload:
        item.title = str(payload["title"])
    if "priority" in payload:
        item.priority = max(1, min(int(payload["priority"]), 100))
    if "notes" in payload:
        item.notes = payload["notes"]
    db.commit()
    return {"id": item.id, "status": item.status, "completed_at": item.completed_at}


@router.post("/import-existing")
def import_existing_records(
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    leads = db.scalars(select(Lead)).all()
    deals = db.scalars(select(Deal)).all()
    linked_leads = 0
    linked_deals = 0
    for lead in leads:
        before = db.scalar(select(WorkspaceEntity.id).where(
            WorkspaceEntity.organization_id == principal.organization_id,
            WorkspaceEntity.entity_type == "lead",
            WorkspaceEntity.entity_id == lead.id,
        ))
        _workspace_link(db, principal.organization_id, "lead", lead.id)
        linked_leads += 0 if before else 1
    for deal in deals:
        before = db.scalar(select(WorkspaceEntity.id).where(
            WorkspaceEntity.organization_id == principal.organization_id,
            WorkspaceEntity.entity_type == "deal",
            WorkspaceEntity.entity_id == deal.id,
        ))
        _workspace_link(db, principal.organization_id, "deal", deal.id)
        linked_deals += 0 if before else 1
    db.commit()
    return {"linked_leads": linked_leads, "linked_deals": linked_deals}

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .autonomy import AUTONOMY_AGENTS, create_task, run_agent, run_task
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .models import AgentRun, Approval, Buyer, Campaign, Deal, Offer, OpsTask, Property
from .operating_system import buyer_appetite, build_seller_offer, initialize_closing
from .schemas import BuyerCreate

router = APIRouter(prefix="/workspace", tags=["workspace operations"])


def linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def activity(db: Session, principal: Principal, kind: str, summary: str,
             deal_id: int | None = None, metadata: dict | None = None) -> None:
    db.add(CrmActivity(organization_id=principal.organization_id, user_id=principal.user_id,
                       deal_id=deal_id, activity_type=kind, summary=summary,
                       metadata_json=metadata or {}))


@router.get("/dashboard")
def dashboard(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_ids = linked_ids(db, principal.organization_id, "lead")
    deal_ids = linked_ids(db, principal.organization_id, "deal")
    buyer_ids = linked_ids(db, principal.organization_id, "buyer")
    task_ids = linked_ids(db, principal.organization_id, "task")
    approval_ids = linked_ids(db, principal.organization_id, "approval")
    campaign_ids = linked_ids(db, principal.organization_id, "campaign")
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all() if deal_ids else []
    tasks = db.scalars(select(OpsTask).where(OpsTask.id.in_(task_ids))).all() if task_ids else []
    approvals = db.scalars(select(Approval).where(Approval.id.in_(approval_ids))).all() if approval_ids else []
    return {
        "organization": {"id": principal.organization_id, "name": principal.organization_name},
        "total_leads": len(lead_ids), "qualified_buyers": len(buyer_ids),
        "active_deals": len([x for x in deals if x.stage not in {"closed", "dead"}]),
        "projected_assignment_revenue": sum(x.projected_assignment_fee or 0 for x in deals if x.stage not in {"closed", "dead"}),
        "queued_tasks": len([x for x in tasks if x.status == "queued"]),
        "completed_tasks": len([x for x in tasks if x.status == "completed"]),
        "pending_approvals": len([x for x in approvals if x.status == "pending"]),
        "campaigns": len(campaign_ids), "autonomy_mode": "supervised_autonomous",
    }


@router.post("/buyers")
def create_buyer(payload: BuyerCreate, principal: Principal = Depends(require_role("disposition")),
                 db: Session = Depends(get_db)):
    buyer = Buyer(**payload.model_dump())
    db.add(buyer); db.flush()
    _workspace_link(db, principal.organization_id, "buyer", buyer.id)
    activity(db, principal, "buyer_created", f"Buyer created: {buyer.name}", metadata={"buyer_id": buyer.id})
    db.commit()
    return {"id": buyer.id, "name": buyer.name}


@router.get("/buyers")
def buyers(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = linked_ids(db, principal.organization_id, "buyer")
    rows = db.scalars(select(Buyer).where(Buyer.id.in_(ids)).order_by(Buyer.reliability_score.desc())).all() if ids else []
    return [{"id": x.id, "name": x.name, "company": x.company, "buyer_type": x.buyer_type,
             "phone": x.phone, "email": x.email, "zip_codes": x.zip_codes, "asset_types": x.asset_types,
             "min_price": x.min_price, "max_price": x.max_price, "max_rehab": x.max_rehab,
             "closing_days": x.closing_days, "proof_of_funds_verified": x.proof_of_funds_verified,
             "response_rate": x.response_rate, "reliability_score": x.reliability_score} for x in rows]


@router.get("/deals")
def deals(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = linked_ids(db, principal.organization_id, "deal")
    rows = db.scalars(select(Deal).where(Deal.id.in_(ids)).order_by(Deal.updated_at.desc())).all() if ids else []
    return [{"id": x.id, "property_id": x.property_id, "stage": x.stage, "strategy": x.strategy,
             "target_contract_price": x.target_contract_price, "target_buyer_price": x.target_buyer_price,
             "projected_assignment_fee": x.projected_assignment_fee, "probability_to_close": x.probability_to_close,
             "risk_score": x.risk_score, "next_action": x.next_action} for x in rows]


@router.get("/properties/{property_id}/buyer-appetite")
def appetite(property_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    _assert_linked(db, principal, "lead", prop.lead_id)
    result = buyer_appetite(db, property_id)
    allowed = set(linked_ids(db, principal.organization_id, "buyer"))
    result["buyers"] = [x for x in result.get("buyers", []) if x.get("buyer_id") in allowed]
    result["matched_buyers"] = len(result["buyers"])
    return result


@router.post("/deals/{deal_id}/seller-offer")
def seller_offer(deal_id: int, payload: dict | None = None,
                 principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    _assert_linked(db, principal, "deal", deal_id)
    try:
        offer, approval = build_seller_offer(db, deal_id, (payload or {}).get("amount"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _workspace_link(db, principal.organization_id, "offer", offer.id)
    _workspace_link(db, principal.organization_id, "approval", approval.id)
    activity(db, principal, "seller_offer_prepared", f"Seller offer prepared for ${offer.amount:,.0f}",
             deal_id=deal_id, metadata={"offer_id": offer.id, "approval_id": approval.id})
    db.commit()
    return {"offer_id": offer.id, "amount": offer.amount, "status": offer.status,
            "approval_id": approval.id, "approval_required": True}


@router.post("/deals/{deal_id}/closing")
def closing(deal_id: int, principal: Principal = Depends(require_role("transaction_coordinator")),
            db: Session = Depends(get_db)):
    _assert_linked(db, principal, "deal", deal_id)
    try:
        items = initialize_closing(db, deal_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    activity(db, principal, "closing_initialized", f"Closing checklist initialized for deal #{deal_id}", deal_id=deal_id)
    db.commit()
    return {"deal_id": deal_id, "items": [{"id": x.id, "type": x.item_type, "status": x.status} for x in items]}


@router.get("/autonomy/status")
def autonomy_status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    task_ids = linked_ids(db, principal.organization_id, "task")
    approval_ids = linked_ids(db, principal.organization_id, "approval")
    campaign_ids = linked_ids(db, principal.organization_id, "campaign")
    run_ids = linked_ids(db, principal.organization_id, "agent_run")
    tasks = db.scalars(select(OpsTask).where(OpsTask.id.in_(task_ids)).order_by(OpsTask.created_at.desc())).all() if task_ids else []
    approvals = db.scalars(select(Approval).where(Approval.id.in_(approval_ids)).order_by(Approval.created_at.desc())).all() if approval_ids else []
    campaigns = db.scalars(select(Campaign).where(Campaign.id.in_(campaign_ids)).order_by(Campaign.created_at.desc())).all() if campaign_ids else []
    runs = db.scalars(select(AgentRun).where(AgentRun.id.in_(run_ids)).order_by(AgentRun.created_at.desc())).all() if run_ids else []
    return {"mode": "supervised_autonomous", "agents": AUTONOMY_AGENTS,
            "tasks": [{"id": x.id, "type": x.task_type, "status": x.status, "priority": x.priority,
                       "lead_id": x.lead_id, "result": x.result, "error": x.error} for x in tasks[:100]],
            "approvals": [{"id": x.id, "action_type": x.action_type, "status": x.status,
                           "summary": x.summary, "entity_type": x.entity_type, "entity_id": x.entity_id} for x in approvals[:100]],
            "agent_runs": [{"id": x.id, "agent_name": x.agent_name, "objective": x.objective,
                            "status": x.status, "confidence": x.confidence, "output": x.output_json} for x in runs[:50]],
            "campaigns": [{"id": x.id, "name": x.name, "type": x.campaign_type, "status": x.status,
                           "audience_count": x.audience_count, "sent_count": x.sent_count,
                           "response_count": x.response_count} for x in campaigns[:100]]}


@router.post("/autonomy/run")
def autonomy_run(payload: dict | None = None, principal: Principal = Depends(require_role("manager")),
                 db: Session = Depends(get_db)):
    payload = payload or {}
    run = run_agent(db, str(payload.get("agent_name") or "executive-orchestrator"),
                    str(payload.get("objective") or "Run workspace wholesale operations"),
                    {**(payload.get("input") or {}), "organization_id": principal.organization_id})
    _workspace_link(db, principal.organization_id, "agent_run", run.id)
    task_id = run.output_json.get("task_id") if isinstance(run.output_json, dict) else None
    if task_id:
        _workspace_link(db, principal.organization_id, "task", int(task_id))
    activity(db, principal, "agent_run", f"{run.agent_name} completed: {run.objective}",
             metadata={"agent_run_id": run.id, "confidence": run.confidence})
    db.commit()
    return {"id": run.id, "agent_name": run.agent_name, "status": run.status,
            "confidence": run.confidence, "output": run.output_json}


@router.post("/autonomy/tasks")
def enqueue_task(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    lead_id = payload.get("lead_id")
    if lead_id is not None:
        _assert_linked(db, principal, "lead", int(lead_id))
    task = create_task(db, str(payload.get("task_type") or "daily_orchestration"),
                       {**(payload.get("payload") or {}), "organization_id": principal.organization_id},
                       priority=int(payload.get("priority") or 50), lead_id=lead_id,
                       buyer_id=payload.get("buyer_id"), requires_approval=bool(payload.get("requires_approval", False)))
    _workspace_link(db, principal.organization_id, "task", task.id)
    db.commit()
    return {"id": task.id, "status": task.status, "task_type": task.task_type}


@router.post("/autonomy/execute")
def execute_tasks(payload: dict | None = None, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    allowed = set(linked_ids(db, principal.organization_id, "task"))
    limit = max(1, min(int((payload or {}).get("limit", 10)), 50))
    queued = db.scalars(select(OpsTask).where(OpsTask.id.in_(allowed), OpsTask.status == "queued")
                        .order_by(OpsTask.priority.desc(), OpsTask.created_at.asc()).limit(limit)).all() if allowed else []
    completed = [run_task(db, task) for task in queued]
    return {"executed": len(completed), "tasks": [{"id": x.id, "type": x.task_type,
            "status": x.status, "result": x.result, "error": x.error} for x in completed]}


@router.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: int, payload: dict, principal: Principal = Depends(require_role("owner")),
                    db: Session = Depends(get_db)):
    _assert_linked(db, principal, "approval", approval_id)
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    decision = str(payload.get("decision") or "").lower()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Decision must be approved or rejected")
    approval.status = decision; approval.decided_by = principal.email
    approval.decision_note = payload.get("note"); approval.decided_at = datetime.utcnow()
    if approval.entity_type == "campaign":
        campaign = db.get(Campaign, approval.entity_id)
        if campaign:
            campaign.status = "ready" if decision == "approved" else "rejected"
    if approval.entity_type == "offer":
        offer = db.get(Offer, approval.entity_id)
        if offer:
            offer.status = "approved" if decision == "approved" else "rejected"
    activity(db, principal, "approval_decided", f"{approval.action_type}: {decision}",
             metadata={"approval_id": approval.id, "entity_type": approval.entity_type,
                       "entity_id": approval.entity_id})
    db.commit()
    return {"id": approval.id, "status": approval.status}

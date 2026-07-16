from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .autonomy import AUTONOMY_AGENTS, create_task, execute_next_tasks, run_agent
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .models import AgentRun, Approval, Buyer, Campaign, Deal, Offer, OpsTask, Property
from .operating_system import buyer_appetite, build_seller_offer, initialize_closing
from .schemas import BuyerCreate

router = APIRouter(prefix="/workspace", tags=["workspace operations"])


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _record_activity(db: Session, principal: Principal, activity_type: str, summary: str,
                     deal_id: int | None = None, metadata: dict | None = None) -> None:
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deal_id=deal_id,
        activity_type=activity_type,
        summary=summary,
        metadata_json=metadata or {},
    ))


@router.get("/dashboard")
def workspace_dashboard(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    deal_ids = _linked_ids(db, principal.organization_id, "deal")
    buyer_ids = _linked_ids(db, principal.organization_id, "buyer")
    task_ids = _linked_ids(db, principal.organization_id, "task")
    approval_ids = _linked_ids(db, principal.organization_id, "approval")
    campaign_ids = _linked_ids(db, principal.organization_id, "campaign")
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all() if deal_ids else []
    tasks = db.scalars(select(OpsTask).where(OpsTask.id.in_(task_ids))).all() if task_ids else []
    approvals = db.scalars(select(Approval).where(Approval.id.in_(approval_ids))).all() if approval_ids else []
    return {
        "organization": {"id": principal.organization_id, "name": principal.organization_name},
        "total_leads": len(lead_ids),
        "qualified_buyers": len(buyer_ids),
        "active_deals": len([item for item in deals if item.stage not in {"closed", "dead"}]),
        "projected_assignment_revenue": sum(item.projected_assignment_fee or 0 for item in deals if item.stage not in {"closed", "dead"}),
        "queued_tasks": len([item for item in tasks if item.status == "queued"]),
        "completed_tasks": len([item for item in tasks if item.status == "completed"]),
        "pending_approvals": len([item for item in approvals if item.status == "pending"]),
        "campaigns": len(campaign_ids),
        "autonomy_mode": "supervised_autonomous",
    }


@router.post("/buyers")
def create_workspace_buyer(payload: BuyerCreate,
                           principal: Principal = Depends(require_role("disposition")),
                           db: Session = Depends(get_db)):
    buyer = Buyer(**payload.model_dump())
    db.add(buyer)
    db.flush()
    _workspace_link(db, principal.organization_id, "buyer", buyer.id)
    _record_activity(db, principal, "buyer_created", f"Buyer created: {buyer.name}", metadata={"buyer_id": buyer.id})
    db.commit()
    return {"id": buyer.id, "name": buyer.name}


@router.get("/buyers")
def list_workspace_buyers(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = _linked_ids(db, principal.organization_id, "buyer")
    rows = db.scalars(select(Buyer).where(Buyer.id.in_(ids)).order_by(Buyer.reliability_score.desc())).all() if ids else []
    return [{
        "id": item.id, "name": item.name, "company": item.company, "buyer_type": item.buyer_type,
        "phone": item.phone, "email": item.email, "zip_codes": item.zip_codes,
        "asset_types": item.asset_types, "min_price": item.min_price, "max_price": item.max_price,
        "max_rehab": item.max_rehab, "closing_days": item.closing_days,
        "proof_of_funds_verified": item.proof_of_funds_verified,
        "response_rate": item.response_rate, "reliability_score": item.reliability_score,
    } for item in rows]


@router.get("/deals")
def list_workspace_deals(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = _linked_ids(db, principal.organization_id, "deal")
    rows = db.scalars(select(Deal).where(Deal.id.in_(ids)).order_by(Deal.updated_at.desc())).all() if ids else []
    return [{
        "id": item.id, "property_id": item.property_id, "stage": item.stage, "strategy": item.strategy,
        "target_contract_price": item.target_contract_price, "target_buyer_price": item.target_buyer_price,
        "projected_assignment_fee": item.projected_assignment_fee,
        "probability_to_close": item.probability_to_close, "risk_score": item.risk_score,
        "next_action": item.next_action,
    } for item in rows]


@router.get("/properties/{property_id}/buyer-appetite")
def workspace_buyer_appetite(property_id: int, principal: Principal = Depends(get_principal),
                             db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    _assert_linked(db, principal, "lead", prop.lead_id)
    result = buyer_appetite(db, property_id)
    allowed = set(_linked_ids(db, principal.organization_id, "buyer"))
    result["buyers"] = [item for item in result.get("buyers", []) if item.get("buyer_id") in allowed]
    result["matched_buyers"] = len(result["buyers"])
    return result


@router.post("/deals/{deal_id}/seller-offer")
def create_workspace_offer(deal_id: int, payload: dict | None = None,
                           principal: Principal = Depends(require_role("manager")),
                           db: Session = Depends(get_db)):
    _assert_linked(db, principal, "deal", deal_id)
    try:
        offer, approval = build_seller_offer(db, deal_id, (payload or {}).get("amount"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _workspace_link(db, principal.organization_id, "offer", offer.id)
    _workspace_link(db, principal.organization_id, "approval", approval.id)
    _record_activity(db, principal, "seller_offer_prepared", f"Seller offer prepared for ${offer.amount:,.0f}",
                     deal_id=deal_id, metadata={"offer_id": offer.id, "approval_id": approval.id})
    db.commit()
    return {"offer_id": offer.id, "amount": offer.amount, "status": offer.status,
            "approval_id": approval.id, "approval_required": True}


@router.post("/deals/{deal_id}/closing")
def start_workspace_closing(deal_id: int, principal: Principal = Depends(require_role("transaction_coordinator")),
                            db: Session = Depends(get_db)):
    _assert_linked(db, principal, "deal", deal_id)
    try:
        items = initialize_closing(db, deal_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    _record_activity(db, principal, "closing_initialized", f"Closing checklist initialized for deal #{deal_id}", deal_id=deal_id)
    db.commit()
    return {"deal_id": deal_id, "items": [{"id": item.id, "type": item.item_type, "status": item.status} for item in items]}


@router.get("/autonomy/status")
def workspace_autonomy_status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    task_ids = _linked_ids(db, principal.organization_id, "task")
    approval_ids = _linked_ids(db, principal.organization_id, "approval")
    campaign_ids = _linked_ids(db, principal.organization_id, "campaign")
    run_ids = _linked_ids(db, principal.organization_id, "agent_run")
    tasks = db.scalars(select(OpsTask).where(OpsTask.id.in_(task_ids)).order_by(OpsTask.created_at.desc())).all() if task_ids else []
    approvals = db.scalars(select(Approval).where(Approval.id.in_(approval_ids)).order_by(Approval.created_at.desc())).all() if approval_ids else []
    campaigns = db.scalars(select(Campaign).where(Campaign.id.in_(campaign_ids)).order_by(Campaign.created_at.desc())).all() if campaign_ids else []
    runs = db.scalars(select(AgentRun).where(AgentRun.id.in_(run_ids)).order_by(AgentRun.created_at.desc())).all() if run_ids else []
    return {
        "mode": "supervised_autonomous", "agents": AUTONOMY_AGENTS,
        "tasks": [{"id": item.id, "type": item.task_type, "status": item.status, "priority": item.priority,
                   "lead_id": item.lead_id, "result": item.result, "error": item.error} for item in tasks[:100]],
        "approvals": [{"id": item.id, "action_type": item.action_type, "status": item.status,
                       "summary": item.summary, "entity_type": item.entity_type, "entity_id": item.entity_id} for item in approvals[:100]],
        "agent_runs": [{"id": item.id, "agent_name": item.agent_name, "objective": item.objective,
                        "status": item.status, "confidence": item.confidence, "output": item.output_json} for item in runs[:50]],
        "campaigns": [{"id": item.id, "name": item.name, "type": item.campaign_type,
                       "status": item.status, "audience_count": item.audience_count,
                       "sent_count": item.sent_count, "response_count": item.response_count} for item in campaigns[:100]],
    }


@router.post("/autonomy/run")
def run_workspace_orchestrator(payload: dict | None = None,
                               principal: Principal = Depends(require_role("manager")),
                               db: Session = Depends(get_db)):
    payload = payload or {}
    run = run_agent(db, str(payload.get("agent_name") or "executive-orchestrator"),
                    str(payload.get("objective") or "Run workspace wholesale operations"),
                    {**(payload.get("input") or {}), "organization_id": principal.organization_id})
    _workspace_link(db, principal.organization_id, "agent_run", run.id)
    task_id = run.output_json.get("task_id") if isinstance(run.output_json, dict) else None
    if task_id:
        _workspace_link(db, principal.organization_id, "task", int(task_id))
    _record_activity(db, principal, "agent_run", f"{run.agent_name} completed: {run.objective}",
                     metadata={"agent_run_id": run.id, "confidence": run.confidence})
    db.commit()
    return {"id": run.id, "agent_name": run.agent_name, "status": run.status,
            "confidence": run.confidence, "output": run.output_json}


@router.post("/autonomy/tasks")
def enqueue_workspace_task(payload: dict, principal: Principal = Depends(require_role("manager")),
                           db: Session = Depends(get_db)):
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
def execute_workspace_tasks(payload: dict | None = None,
                            principal: Principal = Depends(require_role("manager")),
                            db: Session = Depends(get_db)):
    allowed_ids = set(_linked_ids(db, principal.organization_id, "task"))
    limit = max(1, min(int((payload or {}).get("limit", 10)), 50))
    queued = db.scalars(select(OpsTask).where(OpsTask.id.in_(allowed_ids), OpsTask.status == "queued")
                        .order_by(OpsTask.priority.desc(), OpsTask.created_at.asc()).limit(limit)).all() if allowed_ids else []
    completed = []
    for task in queued:
        result = execute_next_tasks(db, 1)
        completed.extend(result)
    return {"executed": len(completed), "tasks": [{"id": item.id, "type": item.task_type,
            "status": item.status, "result": item.result, "error": item.error} for item in completed]}


@router.post("/approvals/{approval_id}/decision")
def decide_workspace_approval(approval_id: int, payload: dict,
                              principal: Principal = Depends(require_role("owner")),
                              db: Session = Depends(get_db)):
    _assert_linked(db, principal, "approval", approval_id)
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    decision = str(payload.get("decision") or "").lower()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Decision must be approved or rejected")
    approval.status = decision
    approval.decided_by = principal.email
    approval.decision_note = payload.get("note")
    if approval.entity_type == "campaign":
        campaign = db.get(Campaign, approval.entity_id)
        if campaign:
            campaign.status = "ready" if decision == "approved" else "rejected"
    if approval.entity_type == "offer":
        offer = db.get(Offer, approval.entity_id)
        if offer:
            offer.status = "approved" if decision == "approved" else "rejected"
    _record_activity(db, principal, "approval_decided", f"{approval.action_type}: {decision}",
                     metadata={"approval_id": approval.id, "entity_type": approval.entity_type,
                               "entity_id": approval.entity_id})
    db.commit()
    return {"id": approval.id, "status": approval.status}

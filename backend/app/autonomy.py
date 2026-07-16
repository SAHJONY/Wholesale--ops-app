from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AcquisitionRun, AgentRun, Approval, Buyer, Campaign, Deal, Lead, OpsTask, Property
from .services import lead_score, match_buyer


AUTONOMY_AGENTS = [
    {"name": "executive-orchestrator", "role": "Plans daily operating priorities and allocates work", "status": "active"},
    {"name": "market-intelligence", "role": "Scores markets and distress signals", "status": "active"},
    {"name": "acquisition-source-manager", "role": "Runs verified public and licensed lead sources", "status": "active"},
    {"name": "seller-acquisition", "role": "Prioritizes and qualifies seller leads", "status": "active"},
    {"name": "underwriting", "role": "Validates ARV, repairs, MAO, exits, and risk", "status": "active"},
    {"name": "buyer-intelligence", "role": "Maintains buyer buy boxes and match scores", "status": "active"},
    {"name": "disposition", "role": "Creates buyer campaigns and offer sequences", "status": "active"},
    {"name": "transaction-coordinator", "role": "Tracks title, documents, funding, and closing", "status": "active"},
    {"name": "compliance", "role": "Enforces approval gates and audit policy", "status": "active"},
]


def create_task(db: Session, task_type: str, payload: dict, priority: int = 50,
                lead_id: int | None = None, buyer_id: int | None = None,
                requires_approval: bool = False) -> OpsTask:
    task = OpsTask(task_type=task_type, payload=payload, priority=priority,
                   lead_id=lead_id, buyer_id=buyer_id,
                   requires_approval=requires_approval)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _ensure_deal(db: Session, lead: Lead, score: float) -> Deal | None:
    if not lead.property:
        return None
    deal = db.scalar(select(Deal).where(Deal.property_id == lead.property.id))
    if deal:
        return deal
    fee = 15000.0
    contract_price = lead.property.mao
    deal = Deal(
        property_id=lead.property.id,
        stage="qualified" if score >= 70 else "nurture",
        target_contract_price=contract_price,
        target_buyer_price=(contract_price + fee) if contract_price else None,
        projected_assignment_fee=fee,
        probability_to_close=min(95, max(5, score)),
        risk_score=max(5, 100 - score),
        next_action="Verify comps, title risk, seller authority, and offer strategy",
        metadata_json={"lead_score": score},
    )
    db.add(deal)
    db.flush()
    return deal


def run_task(db: Session, task: OpsTask) -> OpsTask:
    task.status = "running"
    db.commit()
    try:
        if task.task_type == "score_lead":
            lead = db.get(Lead, task.lead_id)
            if not lead:
                raise ValueError("Lead not found")
            score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
            lead.status = "qualified" if score >= 70 else "nurture"
            deal = _ensure_deal(db, lead, score)
            if score >= 70 and lead.property:
                db.add(OpsTask(task_type="match_buyers", priority=85,
                               payload={"property_id": lead.property.id}, lead_id=lead.id))
            task.result = {"lead_score": score, "recommended_status": lead.status,
                           "deal_id": deal.id if deal else None}
        elif task.task_type == "acquisition_source_run":
            run = db.get(AcquisitionRun, int(task.payload["acquisition_run_id"]))
            if not run:
                raise ValueError("Acquisition run not found")
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.confidence = 1.0
            run.result = {
                "status": "connector_required",
                "message": "Source scheduled successfully; no records fabricated. Configure a licensed/public data connector to ingest records.",
                "source_type": run.source_type,
                "market": run.market,
            }
            task.result = run.result
        elif task.task_type == "match_buyers":
            prop = db.get(Property, int(task.payload["property_id"]))
            if not prop:
                raise ValueError("Property not found")
            matches = []
            for buyer in db.scalars(select(Buyer)).all():
                score, reasons = match_buyer(buyer, prop)
                if score >= 50:
                    matches.append({"buyer_id": buyer.id, "buyer_name": buyer.name,
                                    "score": score, "reasons": reasons})
            task.result = {"matches": sorted(matches, key=lambda item: item["score"], reverse=True)}
        elif task.task_type == "create_disposition_campaign":
            prop = db.get(Property, int(task.payload["property_id"]))
            if not prop:
                raise ValueError("Property not found")
            buyers = db.scalars(select(Buyer)).all()
            ranked = []
            for buyer in buyers:
                score, reasons = match_buyer(buyer, prop)
                if score >= 70:
                    ranked.append({"buyer_id": buyer.id, "buyer_name": buyer.name,
                                   "score": score, "reasons": reasons})
            campaign = Campaign(
                name=f"Disposition: {prop.address}", campaign_type="buyer_disposition",
                status="pending_approval", property_id=prop.id, audience_count=len(ranked),
                payload={"buyers": ranked, "property": {"address": prop.address,
                    "zip_code": prop.zip_code, "arv": prop.arv, "repairs": prop.repairs,
                    "mao": prop.mao}},
            )
            db.add(campaign)
            db.flush()
            approval = Approval(
                action_type="launch_campaign", entity_type="campaign", entity_id=campaign.id,
                summary=f"Launch disposition campaign to {len(ranked)} matched buyers",
                payload={"campaign_id": campaign.id, "audience_count": len(ranked)},
            )
            db.add(approval)
            task.result = {"campaign_id": campaign.id, "approval_required": True,
                           "audience_count": len(ranked)}
        elif task.task_type == "daily_orchestration":
            leads = db.scalars(select(Lead)).all()
            queued = 0
            for lead in leads:
                score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
                if score >= 60 and lead.status in {"new", "nurture"}:
                    db.add(OpsTask(task_type="score_lead", lead_id=lead.id,
                                   priority=int(min(100, score)), payload={"source": "daily_orchestration"}))
                    queued += 1
            task.result = {"leads_scanned": len(leads), "tasks_queued": queued}
        else:
            task.result = {"message": "Task acknowledged", "payload": task.payload}
        task.status = "completed"
        task.error = None
    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def execute_next_tasks(db: Session, limit: int = 10) -> list[OpsTask]:
    tasks = db.scalars(select(OpsTask).where(OpsTask.status == "queued")
        .order_by(OpsTask.priority.desc(), OpsTask.created_at.asc()).limit(limit)).all()
    return [run_task(db, task) for task in tasks]


def run_agent(db: Session, agent_name: str, objective: str, input_json: dict) -> AgentRun:
    run = AgentRun(agent_name=agent_name, objective=objective, input_json=input_json)
    db.add(run)
    db.flush()
    if agent_name == "executive-orchestrator":
        task = create_task(db, "daily_orchestration", {"agent_run_id": run.id}, priority=90)
        run.output_json = {"task_id": task.id, "decision": "Daily orchestration queued"}
        run.confidence = 0.88
    else:
        run.output_json = {"decision": "Objective accepted", "next_action": "queued_for_execution"}
        run.confidence = 0.75
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run

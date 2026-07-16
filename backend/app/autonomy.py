from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentRun, Approval, Buyer, Campaign, Lead, OpsTask, Property
from .services import lead_score, match_buyer


AUTONOMY_AGENTS = [
    {"name": "market-intelligence", "role": "Scores markets and distress signals", "status": "active"},
    {"name": "seller-acquisition", "role": "Prioritizes and qualifies seller leads", "status": "active"},
    {"name": "underwriting", "role": "Validates ARV, repairs, MAO, and risk", "status": "active"},
    {"name": "buyer-intelligence", "role": "Maintains buyer buy boxes and match scores", "status": "active"},
    {"name": "disposition", "role": "Creates buyer campaigns and offer sequences", "status": "active"},
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
            task.result = {"lead_score": score, "recommended_status": lead.status}
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
                name=f"Disposition: {prop.address}",
                campaign_type="buyer_disposition",
                status="pending_approval",
                property_id=prop.id,
                audience_count=len(ranked),
                payload={"buyers": ranked, "property": {
                    "address": prop.address, "zip_code": prop.zip_code,
                    "arv": prop.arv, "repairs": prop.repairs, "mao": prop.mao,
                }},
            )
            db.add(campaign)
            db.flush()
            approval = Approval(
                action_type="launch_campaign", entity_type="campaign",
                entity_id=campaign.id,
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
    tasks = db.scalars(
        select(OpsTask).where(OpsTask.status == "queued")
        .order_by(OpsTask.priority.desc(), OpsTask.created_at.asc()).limit(limit)
    ).all()
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

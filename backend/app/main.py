from datetime import datetime
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .autonomy import AUTONOMY_AGENTS, create_task, execute_next_tasks, run_agent
from .config import settings
from .database import Base, engine, get_db
from .models import AgentRun, Approval, Buyer, Call, Campaign, Lead, OpsTask, Property
from .schemas import BuyerCreate, LeadCreate, MatchResult, UnderwriteRequest
from .services import calculate_mao, distress_score, lead_score, match_buyer

Base.metadata.create_all(bind=engine)
app = FastAPI(title="SAHJONY Wholesale Ops API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url, "http://localhost:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "wholesale-ops-api", "version": "0.2.0"}


@app.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead)).all()
    buyers = db.scalars(select(Buyer)).all()
    calls = db.scalars(select(Call)).all()
    tasks = db.scalars(select(OpsTask)).all()
    approvals = db.scalars(select(Approval).where(Approval.status == "pending")).all()
    campaigns = db.scalars(select(Campaign)).all()
    hot = [lead for lead in leads if lead_score(lead.motivation_score, lead.equity_score, lead.distress_score) >= 70]
    return {
        "total_leads": len(leads), "hot_leads": len(hot), "buyers": len(buyers), "calls": len(calls),
        "queued_tasks": len([task for task in tasks if task.status == "queued"]),
        "completed_tasks": len([task for task in tasks if task.status == "completed"]),
        "pending_approvals": len(approvals), "campaigns": len(campaigns),
        "autonomy_mode": "supervised_autonomous",
    }


@app.post("/leads")
def create_lead(payload: LeadCreate, db: Session = Depends(get_db)):
    p = payload.property
    score = distress_score(p.distress_signals)
    mao = calculate_mao(p.arv, p.repairs) if p.arv is not None and p.repairs is not None else None
    lead = Lead(seller_name=payload.seller_name, phone=payload.phone, email=payload.email, source=payload.source,
                motivation_score=payload.motivation_score, equity_score=payload.equity_score, distress_score=score,
                timeline_days=payload.timeline_days, notes=payload.notes)
    lead.property = Property(**p.model_dump(), mao=mao)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    task = create_task(db, "score_lead", {"trigger": "lead_created"}, priority=80,
                       lead_id=lead.id)
    return {"id": lead.id, "property_id": lead.property.id, "distress_score": score,
            "lead_score": lead_score(lead.motivation_score, lead.equity_score, score),
            "mao": mao, "autonomy_task_id": task.id}


@app.get("/leads")
def list_leads(db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead).order_by(Lead.created_at.desc())).all()
    return [{"id": x.id, "property_id": x.property.id if x.property else None,
             "seller_name": x.seller_name, "phone": x.phone, "status": x.status,
             "distress_score": x.distress_score, "motivation_score": x.motivation_score,
             "address": x.property.address if x.property else None,
             "zip_code": x.property.zip_code if x.property else None,
             "mao": x.property.mao if x.property else None} for x in leads]


@app.post("/buyers")
def create_buyer(payload: BuyerCreate, db: Session = Depends(get_db)):
    buyer = Buyer(**payload.model_dump())
    db.add(buyer)
    db.commit()
    db.refresh(buyer)
    return {"id": buyer.id, "name": buyer.name}


@app.post("/underwrite")
def underwrite(payload: UnderwriteRequest):
    mao = calculate_mao(payload.arv, payload.repairs, payload.assignment_fee, payload.mao_factor)
    spread = max(0, payload.arv - payload.repairs - mao)
    return {"arv": payload.arv, "repairs": payload.repairs,
            "assignment_fee": payload.assignment_fee, "mao": mao,
            "gross_opportunity_spread": spread}


@app.get("/properties/{property_id}/matches", response_model=list[MatchResult])
def buyer_matches(property_id: int, db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    results = []
    for buyer in db.scalars(select(Buyer)).all():
        score, reasons = match_buyer(buyer, prop)
        if score >= 50:
            results.append(MatchResult(buyer_id=buyer.id, buyer_name=buyer.name, score=score, reasons=reasons))
    return sorted(results, key=lambda item: item.score, reverse=True)


@app.post("/webhooks/bland")
def bland_webhook(payload: dict, x_webhook_secret: str | None = Header(default=None), db: Session = Depends(get_db)):
    if settings.bland_webhook_secret and x_webhook_secret != settings.bland_webhook_secret:
        raise HTTPException(401, "Invalid webhook secret")
    call_id = str(payload.get("call_id") or payload.get("id") or "")
    if not call_id:
        raise HTTPException(422, "Missing call_id")
    call = db.scalar(select(Call).where(Call.external_call_id == call_id)) or Call(
        external_call_id=call_id, direction=payload.get("direction", "inbound"))
    call.status = payload.get("status", call.status)
    call.transcript = payload.get("transcript")
    call.summary = payload.get("summary")
    call.metadata_json = payload
    db.add(call)
    db.commit()
    return {"accepted": True, "call_id": call_id}


@app.post("/driving-for-dollars")
def driving_for_dollars(payload: LeadCreate, db: Session = Depends(get_db)):
    payload.source = "driving_for_dollars"
    return create_lead(payload, db)


@app.get("/autonomy/agents")
def autonomy_agents():
    return AUTONOMY_AGENTS


@app.get("/autonomy/status")
def autonomy_status(db: Session = Depends(get_db)):
    tasks = db.scalars(select(OpsTask).order_by(OpsTask.created_at.desc())).all()
    approvals = db.scalars(select(Approval).order_by(Approval.created_at.desc())).all()
    runs = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(20)).all()
    campaigns = db.scalars(select(Campaign).order_by(Campaign.created_at.desc())).all()
    return {
        "mode": "supervised_autonomous",
        "agents": AUTONOMY_AGENTS,
        "tasks": [{"id": x.id, "type": x.task_type, "status": x.status, "priority": x.priority,
                   "lead_id": x.lead_id, "result": x.result, "error": x.error} for x in tasks[:50]],
        "approvals": [{"id": x.id, "action_type": x.action_type, "status": x.status,
                       "summary": x.summary, "entity_type": x.entity_type,
                       "entity_id": x.entity_id} for x in approvals[:50]],
        "agent_runs": [{"id": x.id, "agent_name": x.agent_name, "objective": x.objective,
                        "status": x.status, "confidence": x.confidence,
                        "output": x.output_json} for x in runs],
        "campaigns": [{"id": x.id, "name": x.name, "type": x.campaign_type,
                       "status": x.status, "audience_count": x.audience_count,
                       "sent_count": x.sent_count, "response_count": x.response_count} for x in campaigns],
    }


@app.post("/autonomy/run")
def autonomy_run(payload: dict, db: Session = Depends(get_db)):
    agent_name = str(payload.get("agent_name") or "executive-orchestrator")
    objective = str(payload.get("objective") or "Run daily wholesale operations")
    run = run_agent(db, agent_name, objective, payload.get("input") or {})
    return {"id": run.id, "agent_name": run.agent_name, "status": run.status,
            "confidence": run.confidence, "output": run.output_json}


@app.post("/autonomy/tasks")
def enqueue_task(payload: dict, db: Session = Depends(get_db)):
    task_type = str(payload.get("task_type") or "daily_orchestration")
    task = create_task(db, task_type, payload.get("payload") or {},
                       priority=int(payload.get("priority") or 50),
                       lead_id=payload.get("lead_id"), buyer_id=payload.get("buyer_id"),
                       requires_approval=bool(payload.get("requires_approval", False)))
    return {"id": task.id, "status": task.status, "task_type": task.task_type}


@app.post("/autonomy/execute")
def execute_tasks(payload: dict | None = None, db: Session = Depends(get_db)):
    limit = int((payload or {}).get("limit", 10))
    tasks = execute_next_tasks(db, max(1, min(limit, 50)))
    return {"executed": len(tasks), "tasks": [{"id": x.id, "type": x.task_type,
                                                  "status": x.status, "result": x.result,
                                                  "error": x.error} for x in tasks]}


@app.post("/autonomy/disposition/{property_id}")
def create_disposition(property_id: int, db: Session = Depends(get_db)):
    if not db.get(Property, property_id):
        raise HTTPException(404, "Property not found")
    task = create_task(db, "create_disposition_campaign", {"property_id": property_id},
                       priority=95, requires_approval=True)
    return {"task_id": task.id, "status": task.status, "approval_gate": True}


@app.post("/approvals/{approval_id}/decision")
def decide_approval(approval_id: int, payload: dict, db: Session = Depends(get_db)):
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    decision = str(payload.get("decision") or "").lower()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Decision must be approved or rejected")
    approval.status = decision
    approval.decided_by = str(payload.get("decided_by") or "owner")
    approval.decision_note = payload.get("note")
    approval.decided_at = datetime.utcnow()
    if approval.entity_type == "campaign":
        campaign = db.get(Campaign, approval.entity_id)
        if campaign:
            campaign.status = "ready" if decision == "approved" else "rejected"
    db.commit()
    return {"id": approval.id, "status": approval.status}

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .models import Buyer, Call, Lead, Property
from .schemas import BuyerCreate, LeadCreate, MatchResult, UnderwriteRequest
from .services import calculate_mao, distress_score, lead_score, match_buyer

Base.metadata.create_all(bind=engine)
app = FastAPI(title="SAHJONY Wholesale Ops API", version="0.1.0")
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
    return {"status": "ok", "service": "wholesale-ops-api"}


@app.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead)).all()
    buyers = db.scalars(select(Buyer)).all()
    calls = db.scalars(select(Call)).all()
    hot = [lead for lead in leads if lead_score(lead.motivation_score, lead.equity_score, lead.distress_score) >= 70]
    return {"total_leads": len(leads), "hot_leads": len(hot), "buyers": len(buyers), "calls": len(calls)}


@app.post("/leads")
def create_lead(payload: LeadCreate, db: Session = Depends(get_db)):
    p = payload.property
    score = distress_score(p.distress_signals)
    mao = calculate_mao(p.arv, p.repairs) if p.arv is not None and p.repairs is not None else None
    lead = Lead(seller_name=payload.seller_name, phone=payload.phone, email=payload.email, source=payload.source,
                motivation_score=payload.motivation_score, equity_score=payload.equity_score, distress_score=score,
                timeline_days=payload.timeline_days, notes=payload.notes)
    lead.property = Property(**p.model_dump(), mao=mao)
    db.add(lead); db.commit(); db.refresh(lead)
    return {"id": lead.id, "distress_score": score, "lead_score": lead_score(lead.motivation_score, lead.equity_score, score), "mao": mao}


@app.get("/leads")
def list_leads(db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead).order_by(Lead.created_at.desc())).all()
    return [{"id": x.id, "seller_name": x.seller_name, "phone": x.phone, "status": x.status,
             "distress_score": x.distress_score, "motivation_score": x.motivation_score,
             "address": x.property.address if x.property else None, "zip_code": x.property.zip_code if x.property else None,
             "mao": x.property.mao if x.property else None} for x in leads]


@app.post("/buyers")
def create_buyer(payload: BuyerCreate, db: Session = Depends(get_db)):
    buyer = Buyer(**payload.model_dump()); db.add(buyer); db.commit(); db.refresh(buyer)
    return {"id": buyer.id, "name": buyer.name}


@app.post("/underwrite")
def underwrite(payload: UnderwriteRequest):
    mao = calculate_mao(payload.arv, payload.repairs, payload.assignment_fee, payload.mao_factor)
    return {"arv": payload.arv, "repairs": payload.repairs, "assignment_fee": payload.assignment_fee, "mao": mao}


@app.get("/properties/{property_id}/matches", response_model=list[MatchResult])
def buyer_matches(property_id: int, db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if not prop: raise HTTPException(404, "Property not found")
    results = []
    for buyer in db.scalars(select(Buyer)).all():
        score, reasons = match_buyer(buyer, prop)
        if score >= 50: results.append(MatchResult(buyer_id=buyer.id, buyer_name=buyer.name, score=score, reasons=reasons))
    return sorted(results, key=lambda item: item.score, reverse=True)


@app.post("/webhooks/bland")
def bland_webhook(payload: dict, x_webhook_secret: str | None = Header(default=None), db: Session = Depends(get_db)):
    if settings.bland_webhook_secret and x_webhook_secret != settings.bland_webhook_secret:
        raise HTTPException(401, "Invalid webhook secret")
    call_id = str(payload.get("call_id") or payload.get("id") or "")
    if not call_id: raise HTTPException(422, "Missing call_id")
    call = db.scalar(select(Call).where(Call.external_call_id == call_id)) or Call(external_call_id=call_id, direction=payload.get("direction", "inbound"))
    call.status = payload.get("status", call.status); call.transcript = payload.get("transcript"); call.summary = payload.get("summary")
    call.metadata_json = payload
    db.add(call); db.commit()
    return {"accepted": True, "call_id": call_id}


@app.post("/driving-for-dollars")
def driving_for_dollars(payload: LeadCreate, db: Session = Depends(get_db)):
    payload.source = "driving_for_dollars"
    return create_lead(payload, db)

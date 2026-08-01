from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .database import get_db
from .models import Approval, Buyer, ClosingItem, Deal, Lead, Offer, Property

router = APIRouter(prefix="/property-workspace", tags=["property workspace"])


class UnderwritingInput(BaseModel):
    arv: float = Field(gt=0)
    repairs: float = Field(ge=0)
    assignment_fee: float = Field(default=15_000, ge=0)
    mao_factor: float = Field(default=0.70, ge=0.50, le=0.85)
    confidence: float = Field(ge=0, le=1)
    source: str = Field(min_length=2, max_length=120)
    motivation_score: float | None = Field(default=None, ge=0, le=100)
    distress_score: float | None = Field(default=None, ge=0, le=100)
    equity_score: float | None = Field(default=None, ge=0, le=100)


class CreateDealInput(BaseModel):
    owner_confirmed: bool
    confidence: float = Field(ge=0, le=1)
    minimum_confidence: float = Field(default=0.65, ge=0, le=1)
    strategy: str = Field(default="assignment", pattern="^(assignment|double_close|novation)$")


def _linked_property_ids(db: Session, organization_id: int) -> list[int]:
    explicit = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
    )).all())
    lead_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())
    inherited = list(db.scalars(select(Property.id).where(Property.lead_id.in_(lead_ids))).all()) if lead_ids else []
    return sorted(set(explicit + inherited))


def _assert_property_access(db: Session, principal: Principal, property_id: int) -> Property:
    if property_id not in _linked_property_ids(db, principal.organization_id):
        raise HTTPException(404, "Property not found in this workspace")
    item = db.get(Property, property_id)
    if not item:
        raise HTTPException(404, "Property not found")
    return item


def _buyer_zip_codes(buyer: Buyer) -> set[str]:
    values = buyer.zip_codes if isinstance(buyer.zip_codes, list) else []
    return {str(value).strip()[:5] for value in values if str(value).strip()}


def _buyers_for_zip(db: Session, zip_code: str | None, limit: int = 25) -> list[Buyer]:
    normalized = str(zip_code or "").strip()[:5]
    if not normalized:
        return []
    candidates = db.scalars(
        select(Buyer).order_by(Buyer.reliability_score.desc(), Buyer.id.asc()).limit(1000)
    ).all()
    return [buyer for buyer in candidates if normalized in _buyer_zip_codes(buyer)][:limit]


def _decision_snapshot(item: Property, deal: Deal | None = None) -> dict:
    signals = item.distress_signals if isinstance(item.distress_signals, list) else []
    underwriting = next((entry for entry in reversed(signals) if isinstance(entry, dict) and entry.get("type") == "underwriting"), None)
    return {
        "formula": "MAO = ARV × factor − repairs − assignment fee",
        "underwriting": underwriting,
        "ready_for_deal": bool(item.arv and item.arv > 0 and item.mao and item.mao > 0),
        "deal_exists": deal is not None,
    }


def _workspace_payload(db: Session, principal: Principal, item: Property) -> dict:
    lead = db.get(Lead, item.lead_id)
    deal = db.scalar(select(Deal).where(Deal.property_id == item.id))
    activities = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.lead_id == item.lead_id,
    ).order_by(CrmActivity.created_at.desc()).limit(100)).all()
    follow_ups = db.scalars(select(FollowUpTask).where(
        FollowUpTask.organization_id == principal.organization_id,
        FollowUpTask.lead_id == item.lead_id,
    ).order_by(FollowUpTask.created_at.desc()).limit(50)).all()
    offers = db.scalars(select(Offer).where(Offer.deal_id == deal.id).order_by(Offer.created_at.desc())).all() if deal else []
    closing = db.scalars(select(ClosingItem).where(ClosingItem.deal_id == deal.id).order_by(ClosingItem.created_at.asc())).all() if deal else []
    approvals = db.scalars(select(Approval).where(
        Approval.entity_type.in_(["lead", "property", "deal"]),
        Approval.entity_id.in_([item.lead_id, item.id, deal.id if deal else -1]),
    ).order_by(Approval.created_at.desc())).all()
    buyers = _buyers_for_zip(db, item.zip_code)
    return {
        "property": {
            "id": item.id, "address": item.address, "city": item.city, "state": item.state, "zip_code": item.zip_code,
            "property_type": item.property_type, "bedrooms": item.bedrooms, "bathrooms": item.bathrooms, "sqft": item.sqft,
            "asking_price": item.asking_price, "arv": item.arv, "repairs": item.repairs, "mao": item.mao,
            "distress_signals": item.distress_signals or [], "latitude": item.latitude, "longitude": item.longitude,
        },
        "seller": {
            "lead_id": lead.id if lead else None, "name": lead.seller_name if lead else None, "phone": lead.phone if lead else None,
            "email": lead.email if lead else None, "source": lead.source if lead else None, "status": lead.status if lead else None,
            "motivation_score": lead.motivation_score if lead else 0, "distress_score": lead.distress_score if lead else 0,
            "equity_score": lead.equity_score if lead else 0, "timeline_days": lead.timeline_days if lead else None,
        },
        "deal": None if not deal else {
            "id": deal.id, "stage": deal.stage, "strategy": deal.strategy, "target_contract_price": deal.target_contract_price,
            "target_buyer_price": deal.target_buyer_price, "projected_assignment_fee": deal.projected_assignment_fee,
            "probability_to_close": deal.probability_to_close, "risk_score": deal.risk_score, "next_action": deal.next_action,
        },
        "decision": _decision_snapshot(item, deal),
        "timeline": [{"id": row.id, "type": row.activity_type, "summary": row.summary, "metadata": row.metadata_json, "created_at": row.created_at} for row in activities],
        "follow_ups": [{"id": row.id, "title": row.title, "status": row.status, "priority": row.priority, "due_at": row.due_at, "notes": row.notes} for row in follow_ups],
        "offers": [{"id": row.id, "type": row.offer_type, "amount": row.amount, "status": row.status, "recipient_name": row.recipient_name, "terms": row.terms, "created_at": row.created_at} for row in offers],
        "closing": [{"id": row.id, "type": row.item_type, "status": row.status, "owner": row.owner, "due_at": row.due_at, "notes": row.notes} for row in closing],
        "approvals": [{"id": row.id, "action_type": row.action_type, "status": row.status, "summary": row.summary, "created_at": row.created_at} for row in approvals],
        "buyer_matches": [{"id": row.id, "name": row.name, "company": row.company, "closing_days": row.closing_days, "proof_of_funds_verified": row.proof_of_funds_verified, "reliability_score": row.reliability_score} for row in buyers],
        "governance": {"external_actions_require_approval": True, "audit_history_preserved": True},
    }


@router.get("")
def list_property_workspaces(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = _linked_property_ids(db, principal.organization_id)
    properties = db.scalars(select(Property).where(Property.id.in_(ids)).order_by(Property.id.desc())).all() if ids else []
    lead_ids = [item.lead_id for item in properties]
    leads = {item.id: item for item in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()} if lead_ids else {}
    deals = {item.property_id: item for item in db.scalars(select(Deal).where(Deal.property_id.in_(ids))).all()} if ids else {}
    return [{
        "property_id": item.id, "lead_id": item.lead_id,
        "seller_name": leads.get(item.lead_id).seller_name if leads.get(item.lead_id) else None,
        "status": leads.get(item.lead_id).status if leads.get(item.lead_id) else "unknown",
        "address": item.address, "city": item.city, "state": item.state, "zip_code": item.zip_code,
        "arv": item.arv, "repairs": item.repairs, "mao": item.mao,
        "deal_id": deals.get(item.id).id if deals.get(item.id) else None,
        "deal_stage": deals.get(item.id).stage if deals.get(item.id) else None,
        "projected_assignment_fee": deals.get(item.id).projected_assignment_fee if deals.get(item.id) else None,
    } for item in properties]


@router.get("/{property_id}")
def get_property_workspace(property_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _workspace_payload(db, principal, _assert_property_access(db, principal, property_id))


@router.put("/{property_id}/underwriting")
def update_underwriting(property_id: int, payload: UnderwritingInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    item = _assert_property_access(db, principal, property_id)
    lead = db.get(Lead, item.lead_id)
    mao = max(0.0, round(payload.arv * payload.mao_factor - payload.repairs - payload.assignment_fee, 2))
    item.arv = payload.arv
    item.repairs = payload.repairs
    item.mao = mao
    signals = list(item.distress_signals) if isinstance(item.distress_signals, list) else []
    signals.append({
        "type": "underwriting", "source": payload.source, "confidence": payload.confidence,
        "mao_factor": payload.mao_factor, "assignment_fee": payload.assignment_fee,
        "formula": "ARV × factor − repairs − assignment fee",
    })
    item.distress_signals = signals[-50:]
    if lead:
        if payload.motivation_score is not None: lead.motivation_score = payload.motivation_score
        if payload.distress_score is not None: lead.distress_score = payload.distress_score
        if payload.equity_score is not None: lead.equity_score = payload.equity_score
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=None, lead_id=item.lead_id,
        activity_type="underwriting_updated",
        summary=f"Underwriting saved from {payload.source}; MAO calculated at ${mao:,.0f}",
        metadata_json=payload.model_dump() | {"mao": mao},
    ))
    db.commit()
    db.refresh(item)
    return _workspace_payload(db, principal, item)


@router.post("/{property_id}/create-deal")
def create_governed_deal(property_id: int, payload: CreateDealInput, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    item = _assert_property_access(db, principal, property_id)
    if not payload.owner_confirmed:
        raise HTTPException(400, "Explicit owner confirmation is required")
    if payload.confidence < payload.minimum_confidence:
        raise HTTPException(400, f"Underwriting confidence must be at least {payload.minimum_confidence:.0%}")
    if not item.arv or item.arv <= 0 or not item.mao or item.mao <= 0:
        raise HTTPException(400, "Complete valid underwriting before creating a deal")
    existing = db.scalar(select(Deal).where(Deal.property_id == property_id))
    if existing:
        raise HTTPException(409, "A deal already exists for this property")
    underwriting = _decision_snapshot(item).get("underwriting") or {}
    assignment_fee = float(underwriting.get("assignment_fee") or 15_000)
    deal = Deal(
        property_id=property_id, stage="qualified", strategy=payload.strategy,
        target_contract_price=item.mao, target_buyer_price=item.mao + assignment_fee,
        projected_assignment_fee=assignment_fee, probability_to_close=0.10,
        risk_score=max(0, round(100 - payload.confidence * 100, 2)),
        next_action="Owner review and approval required before seller outreach",
        metadata_json={"underwriting_confidence": payload.confidence, "owner_confirmed": True},
    )
    db.add(deal)
    db.flush()
    lead = db.get(Lead, item.lead_id)
    if lead: lead.status = "qualified"
    db.add(Approval(
        action_type="authorize_external_outreach", status="pending", entity_type="deal", entity_id=deal.id,
        summary="Review underwriting and explicitly approve before any seller outreach or external action",
        payload={"property_id": property_id, "deal_id": deal.id, "mao": item.mao, "confidence": payload.confidence},
    ))
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=None, lead_id=item.lead_id, deal_id=deal.id,
        activity_type="deal_created_governed",
        summary="Deal created from completed underwriting; external actions remain approval-gated",
        metadata_json={"strategy": payload.strategy, "confidence": payload.confidence, "mao": item.mao},
    ))
    db.commit()
    db.refresh(item)
    return _workspace_payload(db, principal, item)

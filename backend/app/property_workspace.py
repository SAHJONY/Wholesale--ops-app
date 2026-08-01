from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .database import get_db
from .models import Approval, Buyer, ClosingItem, Deal, Lead, Offer, Property

router = APIRouter(prefix="/property-workspace", tags=["property workspace"])


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
    """Match buyers portably without database-specific JSON containment operators.

    ``buyers.zip_codes`` is stored as SQLAlchemy JSON rather than PostgreSQL JSONB.
    Filtering with ``.contains([zip])`` can therefore compile into a dialect-specific
    operation that fails in production. Fetching the bounded buyer directory and
    applying normalized ZIP membership in Python is portable across SQLite and
    PostgreSQL and keeps an optional buyer match from crashing the property record.
    """
    normalized = str(zip_code or "").strip()[:5]
    if not normalized:
        return []
    candidates = db.scalars(
        select(Buyer).order_by(Buyer.reliability_score.desc(), Buyer.id.asc()).limit(1000)
    ).all()
    return [buyer for buyer in candidates if normalized in _buyer_zip_codes(buyer)][:limit]


@router.get("")
def list_property_workspaces(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ids = _linked_property_ids(db, principal.organization_id)
    properties = db.scalars(select(Property).where(Property.id.in_(ids)).order_by(Property.id.desc())).all() if ids else []
    lead_ids = [item.lead_id for item in properties]
    leads = {item.id: item for item in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()} if lead_ids else {}
    deals = {item.property_id: item for item in db.scalars(select(Deal).where(Deal.property_id.in_(ids))).all()} if ids else {}
    return [{
        "property_id": item.id,
        "lead_id": item.lead_id,
        "seller_name": leads.get(item.lead_id).seller_name if leads.get(item.lead_id) else None,
        "status": leads.get(item.lead_id).status if leads.get(item.lead_id) else "unknown",
        "address": item.address,
        "city": item.city,
        "state": item.state,
        "zip_code": item.zip_code,
        "arv": item.arv,
        "repairs": item.repairs,
        "mao": item.mao,
        "deal_id": deals.get(item.id).id if deals.get(item.id) else None,
        "deal_stage": deals.get(item.id).stage if deals.get(item.id) else None,
        "projected_assignment_fee": deals.get(item.id).projected_assignment_fee if deals.get(item.id) else None,
    } for item in properties]


@router.get("/{property_id}")
def get_property_workspace(property_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    item = _assert_property_access(db, principal, property_id)
    lead = db.get(Lead, item.lead_id)
    deal = db.scalar(select(Deal).where(Deal.property_id == property_id))
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
        Approval.entity_id.in_([item.lead_id, property_id, deal.id if deal else -1]),
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
        "timeline": [{"id": row.id, "type": row.activity_type, "summary": row.summary, "metadata": row.metadata_json, "created_at": row.created_at} for row in activities],
        "follow_ups": [{"id": row.id, "title": row.title, "status": row.status, "priority": row.priority, "due_at": row.due_at, "notes": row.notes} for row in follow_ups],
        "offers": [{"id": row.id, "type": row.offer_type, "amount": row.amount, "status": row.status, "recipient_name": row.recipient_name, "terms": row.terms, "created_at": row.created_at} for row in offers],
        "closing": [{"id": row.id, "type": row.item_type, "status": row.status, "owner": row.owner, "due_at": row.due_at, "notes": row.notes} for row in closing],
        "approvals": [{"id": row.id, "action_type": row.action_type, "status": row.status, "summary": row.summary, "created_at": row.created_at} for row in approvals],
        "buyer_matches": [{"id": row.id, "name": row.name, "company": row.company, "closing_days": row.closing_days, "proof_of_funds_verified": row.proof_of_funds_verified, "reliability_score": row.reliability_score} for row in buyers],
        "governance": {"external_actions_require_approval": True, "audit_history_preserved": True},
    }

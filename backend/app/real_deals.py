from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .database import get_db
from .models import Deal, Lead, Property

router = APIRouter(prefix="/wholesale/real-deals", tags=["real-deals"])

ENTITY_MARKERS = {
    "LLC", "L.L.C", "INC", "INCORPORATED", "CORP", "CORPORATION", "LTD",
    "LIMITED", "LP", "LLP", "HOLDINGS", "PROPERTIES", "INVESTMENTS", "BANK",
    "TRUST", "FOUNDATION", "AUTHORITY", "COUNTY", "CITY OF", "STATE OF",
}


class SourceRef(BaseModel):
    provider: str = Field(min_length=2, max_length=120)
    source_type: str = Field(min_length=2, max_length=80)
    reference: str = Field(min_length=2, max_length=500)
    observed_at: datetime | None = None
    confidence: float = Field(default=0.8, ge=0, le=1)


class RealDealCreate(BaseModel):
    owner_name: str = Field(min_length=3, max_length=160)
    owner_type: Literal["individual", "entity", "unknown"] = "individual"
    owner_mailing_address: str | None = Field(default=None, max_length=255)
    owner_verified: bool = True

    parcel_id: str | None = Field(default=None, max_length=80)
    deed_type: str | None = Field(default=None, max_length=80)
    deed_date: date | None = None
    deed_consideration: float | None = Field(default=None, ge=0)
    deed_instrument: str | None = Field(default=None, max_length=120)

    address: str = Field(min_length=5, max_length=255)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=2)
    zip_code: str = Field(min_length=5, max_length=12)
    property_type: Literal["single_family", "multi_family", "land", "mobile_home"] = "single_family"
    bedrooms: int | None = Field(default=None, ge=0, le=30)
    bathrooms: float | None = Field(default=None, ge=0, le=30)
    sqft: int | None = Field(default=None, ge=0)

    asking_price: float | None = Field(default=None, ge=0)
    arv: float = Field(gt=0)
    repairs: float = Field(ge=0)
    target_contract_price: float = Field(gt=0)
    target_buyer_price: float = Field(gt=0)
    minimum_assignment_fee: float = Field(default=10_000, ge=0)

    distress_signals: list[str] = Field(default_factory=list)
    source_name: str = Field(default="verified_manual_intake", max_length=80)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    sources: list[SourceRef] = Field(min_length=1)

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str) -> str:
        return value.strip().upper()


class RealDealPatch(BaseModel):
    target_contract_price: float | None = Field(default=None, gt=0)
    target_buyer_price: float | None = Field(default=None, gt=0)
    arv: float | None = Field(default=None, gt=0)
    repairs: float | None = Field(default=None, ge=0)
    distress_signals: list[str] | None = None
    notes: str | None = None
    sources: list[SourceRef] | None = None


def _looks_like_entity(name: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9& ]", " ", name.upper())
    return any(marker in normalized for marker in ENTITY_MARKERS)


def _spread(contract_price: float | None, buyer_price: float | None) -> float:
    if contract_price is None or buyer_price is None:
        return 0.0
    return round(float(buyer_price) - float(contract_price), 2)


def _workspace_link(db: Session, organization_id: int, entity_type: str, entity_id: int) -> None:
    existing = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
        WorkspaceEntity.entity_id == entity_id,
    ))
    if existing:
        return
    db.add(WorkspaceEntity(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
    ))


def _assert_deal_linked(db: Session, principal: Principal, deal_id: int) -> None:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
        WorkspaceEntity.entity_id == deal_id,
    ))
    if not linked:
        raise HTTPException(404, "Deal not found in this workspace")


def _serialize(deal: Deal, prop: Property | None, lead: Lead | None) -> dict:
    metadata = deal.metadata_json or {}
    owner = metadata.get("owner") or {}
    deed = metadata.get("deed") or {}
    sources = metadata.get("sources") or []
    spread = _spread(deal.target_contract_price, deal.target_buyer_price)
    source_confidence = 0.0
    if sources:
        source_confidence = round(sum(float(item.get("confidence") or 0) for item in sources) / len(sources), 3)
    record = {
        "deal_id": deal.id,
        "lead_id": lead.id if lead else None,
        "property_id": prop.id if prop else deal.property_id,
        "stage": deal.stage,
        "strategy": deal.strategy,
        "owner": owner,
        "deed": deed,
        "property": {
            "address": prop.address if prop else None,
            "city": prop.city if prop else None,
            "state": prop.state if prop else None,
            "zip_code": prop.zip_code if prop else None,
            "property_type": prop.property_type if prop else None,
            "bedrooms": prop.bedrooms if prop else None,
            "bathrooms": prop.bathrooms if prop else None,
            "sqft": prop.sqft if prop else None,
            "asking_price": prop.asking_price if prop else None,
            "arv": prop.arv if prop else None,
            "repairs": prop.repairs if prop else None,
            "mao": prop.mao if prop else None,
            "distress_signals": prop.distress_signals if prop else [],
        },
        "underwriting": {
            "target_contract_price": deal.target_contract_price,
            "target_buyer_price": deal.target_buyer_price,
            "projected_assignment_fee": spread,
            "minimum_assignment_fee": metadata.get("minimum_assignment_fee", 10_000),
            "meets_10k_target": spread >= 10_000,
            "probability_to_close": deal.probability_to_close,
            "risk_score": deal.risk_score,
        },
        "sources": sources,
        "source_confidence": source_confidence,
        "verification": metadata.get("verification") or {},
        "next_action": deal.next_action,
        "created_at": deal.created_at,
        "updated_at": deal.updated_at,
    }
    record["gate"] = _verification_gate(record)
    return record


def _verification_gate(record: dict, minimum_assignment_fee: float | None = None) -> dict:
    owner = record.get("owner") or {}
    deed = record.get("deed") or {}
    prop = record.get("property") or {}
    underwriting = record.get("underwriting") or {}
    verification = record.get("verification") or {}
    sources = record.get("sources") or []
    communication_gate = ((record.get("metadata") or {}).get("communication_gate") or {})
    minimum = float(minimum_assignment_fee if minimum_assignment_fee is not None else underwriting.get("minimum_assignment_fee") or 10_000)
    spread = float(underwriting.get("projected_assignment_fee") or 0)
    owner_verified = bool(owner.get("verified") or verification.get("owner_verified") or communication_gate.get("seller_authority_verified"))
    title_verified = bool(
        verification.get("title_verified")
        or deed.get("instrument")
        or (deed.get("parcel_id") and verification.get("owner_verified"))
    )
    blockers: list[str] = []
    if (owner.get("type") or "unknown") != "individual":
        blockers.append("individual_owner_not_confirmed")
    if not owner_verified:
        blockers.append("seller_authority_not_verified")
    if not title_verified:
        blockers.append("title_or_deed_evidence_missing")
    if not sources:
        blockers.append("source_evidence_missing")
    if not prop.get("arv"):
        blockers.append("arv_missing")
    if prop.get("repairs") is None:
        blockers.append("repair_scope_missing")
    if not underwriting.get("target_contract_price"):
        blockers.append("contract_target_missing")
    if not underwriting.get("target_buyer_price"):
        blockers.append("buyer_target_missing")
    if spread < minimum:
        blockers.append("assignment_spread_below_minimum")
    return {
        "cleared": not blockers,
        "blockers": blockers,
        "owner_verified": owner_verified,
        "title_verified": title_verified,
        "source_count": len(sources),
        "minimum_assignment_fee": minimum,
        "projected_assignment_fee": spread,
    }


@router.get("")
def list_real_deals(
    state: str | None = Query(default=None, min_length=2, max_length=2),
    property_type: str = Query(default="single_family"),
    owner_type: str | None = Query(default=None),
    min_assignment_fee: float = Query(default=10_000, ge=0),
    verified_only: bool = Query(default=False),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    deal_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
    )).all()
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids)).order_by(Deal.updated_at.desc())).all() if deal_ids else []
    output: list[dict] = []
    for deal in deals:
        prop = db.get(Property, deal.property_id)
        lead = db.get(Lead, prop.lead_id) if prop else None
        record = _serialize(deal, prop, lead)
        record["gate"] = _verification_gate(record, min_assignment_fee)
        if owner_type and (record["owner"].get("type") or "unknown") != owner_type:
            continue
        if property_type and record["property"].get("property_type") != property_type:
            continue
        if state and str(record["property"].get("state") or "").upper() != state.upper():
            continue
        if float(record["underwriting"]["projected_assignment_fee"] or 0) < min_assignment_fee:
            continue
        if verified_only and not record["gate"]["cleared"]:
            continue
        output.append(record)
    return {
        "filters": {
            "state": state.upper() if state else None,
            "property_type": property_type,
            "owner_type": owner_type,
            "min_assignment_fee": min_assignment_fee,
            "verified_only": verified_only,
        },
        "count": len(output),
        "deals": output,
    }


@router.post("")
def create_real_deal(
    payload: RealDealCreate,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    if payload.owner_type != "individual" or _looks_like_entity(payload.owner_name):
        raise HTTPException(422, "Real-deal intake is configured for individual owners only")
    if not payload.owner_verified:
        raise HTTPException(422, "Owner must be verified from a deed, assessor, clerk, or equivalent public record")
    spread = _spread(payload.target_contract_price, payload.target_buyer_price)
    if spread < payload.minimum_assignment_fee:
        raise HTTPException(422, f"Projected assignment spread ${spread:,.0f} is below the configured minimum")
    if payload.target_contract_price >= payload.target_buyer_price:
        raise HTTPException(422, "Buyer price must exceed contract price")

    linked_lead_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    if linked_lead_ids:
        duplicate = db.scalar(select(Property).where(
            Property.lead_id.in_(linked_lead_ids),
            Property.address == payload.address,
            Property.city == payload.city,
            Property.state == payload.state,
            Property.zip_code == payload.zip_code,
        ))
        if duplicate:
            raise HTTPException(409, "This property already exists in the workspace")

    lead = Lead(
        seller_name=payload.owner_name,
        phone=payload.contact_phone or "not_enriched",
        email=payload.contact_email,
        source=payload.source_name,
        status="qualified",
        motivation_score=0,
        equity_score=0,
        distress_score=0,
        notes=payload.notes,
    )
    prop = Property(
        address=payload.address,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        property_type=payload.property_type,
        bedrooms=payload.bedrooms,
        bathrooms=payload.bathrooms,
        sqft=payload.sqft,
        asking_price=payload.asking_price,
        arv=payload.arv,
        repairs=payload.repairs,
        mao=payload.target_buyer_price,
        distress_signals=payload.distress_signals,
    )
    lead.property = prop
    db.add(lead)
    db.flush()

    now = datetime.now(timezone.utc)
    deal = Deal(
        property_id=prop.id,
        stage="qualified",
        strategy="assignment",
        target_contract_price=payload.target_contract_price,
        target_buyer_price=payload.target_buyer_price,
        projected_assignment_fee=spread,
        probability_to_close=0,
        risk_score=50,
        next_action="Verify title, repair scope, comps, and buyer before seller offer",
        metadata_json={
            "owner": {
                "name": payload.owner_name,
                "type": "individual",
                "mailing_address": payload.owner_mailing_address,
                "verified": True,
            },
            "deed": {
                "parcel_id": payload.parcel_id,
                "type": payload.deed_type,
                "date": payload.deed_date.isoformat() if payload.deed_date else None,
                "consideration": payload.deed_consideration,
                "instrument": payload.deed_instrument,
            },
            "sources": [item.model_dump(mode="json") for item in payload.sources],
            "verification": {
                "owner_individual": True,
                "owner_verified": True,
                "source_count": len(payload.sources),
                "ingested_at": now.isoformat(),
                "facts_are_source_bounded": True,
            },
            "minimum_assignment_fee": payload.minimum_assignment_fee,
        },
    )
    db.add(deal)
    db.flush()
    _workspace_link(db, principal.organization_id, "lead", lead.id)
    _workspace_link(db, principal.organization_id, "deal", deal.id)
    db.commit()
    db.refresh(deal)
    return _serialize(deal, prop, lead)


@router.get("/{deal_id}")
def get_real_deal(
    deal_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    _assert_deal_linked(db, principal, deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    lead = db.get(Lead, prop.lead_id) if prop else None
    return _serialize(deal, prop, lead)


@router.patch("/{deal_id}")
def update_real_deal(
    deal_id: int,
    payload: RealDealPatch,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    _assert_deal_linked(db, principal, deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    if not prop:
        raise HTTPException(404, "Deal property not found")

    if payload.arv is not None:
        prop.arv = payload.arv
    if payload.repairs is not None:
        prop.repairs = payload.repairs
    if payload.distress_signals is not None:
        prop.distress_signals = payload.distress_signals
    if payload.target_contract_price is not None:
        deal.target_contract_price = payload.target_contract_price
    if payload.target_buyer_price is not None:
        deal.target_buyer_price = payload.target_buyer_price

    spread = _spread(deal.target_contract_price, deal.target_buyer_price)
    minimum = float((deal.metadata_json or {}).get("minimum_assignment_fee") or 10_000)
    if spread < minimum:
        raise HTTPException(422, f"Updated spread ${spread:,.0f} is below the configured minimum")
    deal.projected_assignment_fee = spread
    prop.mao = deal.target_buyer_price

    metadata = dict(deal.metadata_json or {})
    if payload.sources is not None:
        metadata["sources"] = [item.model_dump(mode="json") for item in payload.sources]
        verification = dict(metadata.get("verification") or {})
        verification["source_count"] = len(payload.sources)
        verification["updated_at"] = datetime.now(timezone.utc).isoformat()
        metadata["verification"] = verification
    if payload.notes is not None:
        metadata["operator_notes"] = payload.notes
    deal.metadata_json = metadata
    db.commit()
    db.refresh(deal)
    lead = db.get(Lead, prop.lead_id)
    return _serialize(deal, prop, lead)

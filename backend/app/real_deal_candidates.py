from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .database import get_db
from .intelligence_models import IntelligenceConflict, IntelligenceFact
from .models import Deal, Lead, Property
from .real_deals import _looks_like_entity, _serialize, _spread, _workspace_link
from .services import calculate_mao

router = APIRouter(prefix="/wholesale/real-deal-candidates", tags=["real-deal-candidates"])

OWNER_FIELDS = {"owner_name", "owner_mailing_address", "apn", "last_sale_price", "last_sale_date"}
ACCEPTED_OWNER_STATUSES = {"verified", "partially_verified"}


def _workspace_leads(db: Session, organization_id: int) -> list[Lead]:
    lead_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    return db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all() if lead_ids else []


def _property_facts(db: Session, organization_id: int, property_id: int) -> list[IntelligenceFact]:
    return db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == organization_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id == property_id,
        IntelligenceFact.field_name.in_(OWNER_FIELDS),
    ).order_by(IntelligenceFact.confidence.desc(), IntelligenceFact.updated_at.desc())).all()


def _has_open_owner_conflict(db: Session, organization_id: int, property_id: int) -> bool:
    conflict = db.scalar(select(IntelligenceConflict.id).where(
        IntelligenceConflict.organization_id == organization_id,
        IntelligenceConflict.entity_type == "property",
        IntelligenceConflict.entity_id == property_id,
        IntelligenceConflict.field_name == "owner_name",
        IntelligenceConflict.status == "open",
    ))
    return bool(conflict)


def _best_fact(facts: list[IntelligenceFact], field_name: str) -> IntelligenceFact | None:
    eligible = [
        fact for fact in facts
        if fact.field_name == field_name and fact.verification_status in ACCEPTED_OWNER_STATUSES
        and fact.value_json.get("value") not in (None, "")
    ]
    return eligible[0] if eligible else None


def _fact_value(facts: list[IntelligenceFact], field_name: str):
    fact = _best_fact(facts, field_name)
    return fact.value_json.get("value") if fact else None


def _source_payload(facts: list[IntelligenceFact]) -> list[dict]:
    output = []
    seen = set()
    for fact in facts:
        if fact.verification_status not in ACCEPTED_OWNER_STATUSES:
            continue
        marker = (fact.source, fact.source_reference)
        if marker in seen:
            continue
        seen.add(marker)
        output.append({
            "provider": fact.source,
            "source_type": "canonical_property_intelligence",
            "reference": fact.source_reference or f"property:{fact.entity_id}:{fact.field_name}",
            "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
            "confidence": round(max(0.0, min(1.0, float(fact.confidence or 0) / 100.0)), 3),
            "verification_status": fact.verification_status,
            "field": fact.field_name,
        })
    return output


def _candidate_for(
    db: Session,
    organization_id: int,
    lead: Lead,
    *,
    factor: float,
    min_assignment_fee: float,
) -> dict | None:
    prop = lead.property
    if not prop or prop.property_type != "single_family":
        return None
    if not prop.arv or prop.repairs is None or not prop.asking_price:
        return None
    if _has_open_owner_conflict(db, organization_id, prop.id):
        return None

    facts = _property_facts(db, organization_id, prop.id)
    owner_fact = _best_fact(facts, "owner_name")
    if not owner_fact:
        return None
    owner_name = str(owner_fact.value_json.get("value") or "").strip()
    if not owner_name or _looks_like_entity(owner_name):
        return None

    theoretical_buyer_price = calculate_mao(float(prop.arv), float(prop.repairs or 0), assignment_fee=0, factor=factor)
    spread = _spread(float(prop.asking_price), theoretical_buyer_price)
    if spread < min_assignment_fee:
        return None

    sources = _source_payload(facts)
    return {
        "lead_id": lead.id,
        "property_id": prop.id,
        "status": "screening_candidate",
        "owner": {
            "name": owner_name,
            "type": "individual",
            "mailing_address": _fact_value(facts, "owner_mailing_address"),
            "verified": owner_fact.verification_status in ACCEPTED_OWNER_STATUSES,
            "verification_status": owner_fact.verification_status,
            "confidence": owner_fact.confidence,
        },
        "deed": {
            "parcel_id": _fact_value(facts, "apn"),
            "date": _fact_value(facts, "last_sale_date"),
            "consideration": _fact_value(facts, "last_sale_price"),
        },
        "property": {
            "address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
            "property_type": prop.property_type,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
            "sqft": prop.sqft,
            "asking_price": prop.asking_price,
            "arv": prop.arv,
            "repairs": prop.repairs,
            "distress_signals": prop.distress_signals or [],
        },
        "screening": {
            "factor": factor,
            "theoretical_buyer_price": theoretical_buyer_price,
            "asking_price": prop.asking_price,
            "projected_assignment_spread": spread,
            "minimum_assignment_fee": min_assignment_fee,
            "formula": "ARV * factor - repairs = theoretical buyer price; buyer price - asking = screening spread",
            "authority": "screening_only_not_an_offer",
        },
        "sources": sources,
        "source_count": len(sources),
        "next_action": "Verify comps, repair scope, title/deed, seller authority, and buyer demand before promotion",
    }


@router.get("")
def list_candidates(
    state: str | None = Query(default=None, min_length=2, max_length=2),
    factor: float = Query(default=0.70, ge=0.50, le=0.90),
    min_assignment_fee: float = Query(default=10_000, ge=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    candidates = []
    for lead in _workspace_leads(db, principal.organization_id):
        candidate = _candidate_for(
            db,
            principal.organization_id,
            lead,
            factor=factor,
            min_assignment_fee=min_assignment_fee,
        )
        if not candidate:
            continue
        if state and str(candidate["property"]["state"] or "").upper() != state.upper():
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: float(item["screening"]["projected_assignment_spread"]), reverse=True)
    return {
        "organization_id": principal.organization_id,
        "filters": {"state": state.upper() if state else None, "factor": factor, "min_assignment_fee": min_assignment_fee},
        "count": len(candidates),
        "candidates": candidates,
        "rules": {
            "property_type": "single_family",
            "owner_type": "individual_only",
            "owner_conflicts_allowed": False,
            "owner_verification_status": sorted(ACCEPTED_OWNER_STATUSES),
            "promotion_is_human_controlled": True,
        },
    }


@router.post("/{property_id}/promote")
def promote_candidate(
    property_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    payload = payload or {}
    minimum = float(payload.get("minimum_assignment_fee") or 10_000)
    factor = float(payload.get("factor") or 0.70)

    leads = _workspace_leads(db, principal.organization_id)
    lead = next((item for item in leads if item.property and item.property.id == property_id), None)
    if not lead or not lead.property:
        raise HTTPException(404, "Property not found in this workspace")

    candidate = _candidate_for(db, principal.organization_id, lead, factor=factor, min_assignment_fee=minimum)
    if not candidate:
        raise HTTPException(422, "Property does not currently satisfy verified real-deal candidate rules")

    existing = db.scalar(select(Deal).where(Deal.property_id == property_id))
    if existing:
        _workspace_link(db, principal.organization_id, "deal", existing.id)
        return _serialize(existing, lead.property, lead)

    contract_price = float(payload.get("target_contract_price") or lead.property.asking_price or 0)
    buyer_price = float(payload.get("target_buyer_price") or candidate["screening"]["theoretical_buyer_price"] or 0)
    spread = _spread(contract_price, buyer_price)
    if spread < minimum:
        raise HTTPException(422, f"Promoted deal spread ${spread:,.0f} is below the configured minimum")

    facts = _property_facts(db, principal.organization_id, property_id)
    sources = _source_payload(facts)
    now = datetime.now(timezone.utc)
    deal = Deal(
        property_id=property_id,
        stage="qualified",
        strategy="assignment",
        target_contract_price=contract_price,
        target_buyer_price=buyer_price,
        projected_assignment_fee=spread,
        probability_to_close=0,
        risk_score=50,
        next_action="Complete comp, rehab, title, seller-authority, and buyer validation before offer approval",
        metadata_json={
            "owner": candidate["owner"],
            "deed": candidate["deed"],
            "sources": sources,
            "verification": {
                "owner_individual": True,
                "owner_conflict_open": False,
                "source_count": len(sources),
                "promoted_from_canonical_intelligence": True,
                "promoted_at": now.isoformat(),
                "facts_are_source_bounded": True,
            },
            "screening": candidate["screening"],
            "minimum_assignment_fee": minimum,
        },
    )
    db.add(deal)
    db.flush()
    _workspace_link(db, principal.organization_id, "deal", deal.id)
    lead.status = "qualified"
    db.commit()
    db.refresh(deal)
    return _serialize(deal, lead.property, lead)

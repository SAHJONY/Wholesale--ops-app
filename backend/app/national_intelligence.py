from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .event_bus import emit_event
from .intelligence_models import CanonicalEntity, IntelligenceFact
from .models import Buyer, Deal, Lead, Property
from .national_intelligence_models import NationalIntelligenceRun, PropertyIntelligenceScore
from .services import distress_score as calculate_distress_score, match_buyer

router = APIRouter(prefix="/national-intelligence", tags=["national property intelligence network"])


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _canonical(db: Session, organization_id: int, property_id: int) -> CanonicalEntity | None:
    return db.scalar(select(CanonicalEntity).where(
        CanonicalEntity.organization_id == organization_id,
        CanonicalEntity.entity_type == "property",
        CanonicalEntity.entity_id == property_id,
    ))


def _buyer_demand(db: Session, organization_id: int, prop: Property) -> tuple[float, int]:
    buyer_ids = _linked_ids(db, organization_id, "buyer")
    if not buyer_ids:
        return 0.0, 0
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all()
    scores = [match_buyer(buyer, prop)[0] for buyer in buyers]
    matches = [score for score in scores if score >= 50]
    if not scores:
        return 0.0, 0
    top = sorted(scores, reverse=True)[:5]
    return round(sum(top) / len(top), 2), len(matches)


def _equity_proxy(prop: Property, canonical_data: dict) -> tuple[float, list[str]]:
    warnings: list[str] = []
    market_value = canonical_data.get("market_value") or prop.arv
    mortgage_balance = canonical_data.get("mortgage_balance")
    asking = prop.asking_price
    if market_value and mortgage_balance is not None:
        equity = max(0.0, float(market_value) - float(mortgage_balance))
        return min(100.0, round((equity / max(float(market_value), 1.0)) * 100, 2)), warnings
    if market_value and asking is not None:
        spread = max(0.0, float(market_value) - float(asking))
        warnings.append("Equity score uses asking-price spread because mortgage balance is unavailable")
        return min(100.0, round((spread / max(float(market_value), 1.0)) * 100, 2)), warnings
    warnings.append("Equity score unavailable; no verified value and debt combination")
    return 0.0, warnings


def _assignment_fee(prop: Property) -> float | None:
    if prop.mao is None:
        return None
    buyer_price = prop.asking_price or prop.arv
    if buyer_price is None:
        return None
    return round(max(0.0, float(buyer_price) - float(prop.mao)), 2)


def _score_property(db: Session, principal: Principal, lead: Lead, prop: Property) -> PropertyIntelligenceScore:
    if str(prop.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")

    canonical = _canonical(db, principal.organization_id, prop.id)
    canonical_data = dict(canonical.canonical_data or {}) if canonical else {}
    confidence = float(canonical.confidence or 0) if canonical else 0.0
    ownership_verified = bool(canonical and canonical.verification_status == "verified" and canonical_data.get("owner_name"))
    distress = calculate_distress_score(prop.distress_signals or [])
    equity, warnings = _equity_proxy(prop, canonical_data)
    demand, matching_buyers = _buyer_demand(db, principal.organization_id, prop)
    fee = _assignment_fee(prop)

    score = (
        distress * 0.30
        + equity * 0.25
        + demand * 0.25
        + confidence * 0.15
        + (100.0 if ownership_verified else 0.0) * 0.05
    )
    reasons = []
    if distress >= 40:
        reasons.append("Strong distress indicators")
    if equity >= 30:
        reasons.append("Meaningful estimated equity or price spread")
    if demand >= 60:
        reasons.append(f"Strong buyer demand from {matching_buyers} matched buyers")
    if ownership_verified:
        reasons.append("County-verified ownership")
    if confidence < 50:
        warnings.append("Canonical data confidence is below 50")
    if not ownership_verified:
        warnings.append("Ownership is not county verified")
    if prop.arv is None or prop.repairs is None:
        warnings.append("ARV or repairs missing; underwriting is incomplete")

    row = db.scalar(select(PropertyIntelligenceScore).where(
        PropertyIntelligenceScore.organization_id == principal.organization_id,
        PropertyIntelligenceScore.property_id == prop.id,
    ))
    if not row:
        row = PropertyIntelligenceScore(
            organization_id=principal.organization_id,
            lead_id=lead.id,
            property_id=prop.id,
            market_key=f"{prop.city}, {prop.state} {prop.zip_code}",
        )
        db.add(row)
    row.market_key = f"{prop.city}, {prop.state} {prop.zip_code}"
    row.opportunity_score = round(min(100.0, score), 2)
    row.distress_score = distress
    row.equity_score = equity
    row.buyer_demand_score = demand
    row.data_confidence = confidence
    row.ownership_verified = ownership_verified
    row.projected_assignment_fee = fee
    row.reasons_json = reasons
    row.warnings_json = warnings
    row.source_summary_json = {
        "canonical_sources": canonical.source_count if canonical else 0,
        "canonical_conflicts": canonical.conflict_count if canonical else 0,
        "matching_buyers": matching_buyers,
        "canonical_status": canonical.verification_status if canonical else "unverified",
    }
    row.calculated_at = datetime.utcnow()
    db.flush()
    return row


def _refresh(db: Session, principal: Principal, trigger: str = "manual", limit: int = 500) -> NationalIntelligenceRun:
    run = NationalIntelligenceRun(organization_id=principal.organization_id, trigger=trigger)
    db.add(run)
    db.flush()
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids)).order_by(Lead.created_at.desc()).limit(limit)).all() if lead_ids else []
    skipped = 0
    scored = []
    for lead in leads:
        if not lead.property or str(lead.property.state or "").upper() == "TX":
            skipped += 1
            continue
        row = _score_property(db, principal, lead, lead.property)
        scored.append(row)
    high_priority = sum(1 for row in scored if row.opportunity_score >= 70)
    run.properties_seen = len(leads)
    run.properties_scored = len(scored)
    run.properties_skipped = skipped
    run.high_priority_count = high_priority
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    run.result_json = {
        "top_property_ids": [row.property_id for row in sorted(scored, key=lambda item: item.opportunity_score, reverse=True)[:20]],
        "high_priority_count": high_priority,
    }
    event = emit_event(
        db, principal.organization_id, "NationalIntelligenceRefreshed", "organization", principal.organization_id,
        payload={"run_id": run.id, "properties_scored": len(scored), "high_priority_count": high_priority},
        source="national_intelligence",
        event_key=f"national-intelligence:{principal.organization_id}:{run.id}",
    )
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="national_intelligence_refreshed",
        summary=f"National property intelligence refreshed for {len(scored)} properties",
        metadata_json={"run_id": run.id, "event_id": event.id, "high_priority_count": high_priority},
    ))
    db.commit()
    return run


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(PropertyIntelligenceScore).where(
        PropertyIntelligenceScore.organization_id == principal.organization_id,
    ).order_by(PropertyIntelligenceScore.opportunity_score.desc()).limit(500)).all()
    runs = db.scalars(select(NationalIntelligenceRun).where(
        NationalIntelligenceRun.organization_id == principal.organization_id,
    ).order_by(NationalIntelligenceRun.started_at.desc()).limit(20)).all()
    markets: dict[str, dict] = {}
    for row in rows:
        market = markets.setdefault(row.market_key, {"properties": 0, "high_priority": 0, "score_total": 0.0, "projected_fees": 0.0})
        market["properties"] += 1
        market["high_priority"] += int(row.opportunity_score >= 70)
        market["score_total"] += row.opportunity_score
        market["projected_fees"] += float(row.projected_assignment_fee or 0)
    market_rows = [{
        "market": key,
        "properties": value["properties"],
        "high_priority": value["high_priority"],
        "average_score": round(value["score_total"] / value["properties"], 2),
        "projected_fees": round(value["projected_fees"], 2),
    } for key, value in markets.items()]
    market_rows.sort(key=lambda item: (item["high_priority"], item["average_score"]), reverse=True)
    return {
        "generated_at": datetime.utcnow(),
        "summary": {
            "properties": len(rows),
            "high_priority": sum(1 for row in rows if row.opportunity_score >= 70),
            "ownership_verified": sum(1 for row in rows if row.ownership_verified),
            "projected_assignment_fees": round(sum(float(row.projected_assignment_fee or 0) for row in rows), 2),
            "average_opportunity_score": round(sum(row.opportunity_score for row in rows) / len(rows), 2) if rows else 0,
        },
        "properties": [{
            "id": row.id,
            "lead_id": row.lead_id,
            "property_id": row.property_id,
            "market": row.market_key,
            "opportunity_score": row.opportunity_score,
            "distress_score": row.distress_score,
            "equity_score": row.equity_score,
            "buyer_demand_score": row.buyer_demand_score,
            "data_confidence": row.data_confidence,
            "ownership_verified": row.ownership_verified,
            "projected_assignment_fee": row.projected_assignment_fee,
            "reasons": row.reasons_json,
            "warnings": row.warnings_json,
            "source_summary": row.source_summary_json,
            "calculated_at": row.calculated_at,
        } for row in rows],
        "markets": market_rows[:100],
        "runs": [{
            "id": run.id,
            "status": run.status,
            "trigger": run.trigger,
            "properties_seen": run.properties_seen,
            "properties_scored": run.properties_scored,
            "properties_skipped": run.properties_skipped,
            "high_priority_count": run.high_priority_count,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        } for run in runs],
    }


@router.post("/refresh")
def refresh(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    limit = max(1, min(2000, int((payload or {}).get("limit") or 500)))
    run = _refresh(db, principal, trigger=str((payload or {}).get("trigger") or "manual"), limit=limit)
    return {"run_id": run.id, "status": run.status, "properties_scored": run.properties_scored, "high_priority_count": run.high_priority_count}


@router.get("/properties/{property_id}")
def property_detail(property_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    property_ids = _linked_ids(db, principal.organization_id, "property")
    if property_id not in property_ids:
        raise HTTPException(404, "Property not found in this workspace")
    row = db.scalar(select(PropertyIntelligenceScore).where(
        PropertyIntelligenceScore.organization_id == principal.organization_id,
        PropertyIntelligenceScore.property_id == property_id,
    ))
    if not row:
        raise HTTPException(404, "Property intelligence has not been calculated")
    facts = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == principal.organization_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id == property_id,
    ).order_by(IntelligenceFact.field_name, IntelligenceFact.confidence.desc())).all()
    return {
        "score": {
            "opportunity_score": row.opportunity_score,
            "distress_score": row.distress_score,
            "equity_score": row.equity_score,
            "buyer_demand_score": row.buyer_demand_score,
            "data_confidence": row.data_confidence,
            "ownership_verified": row.ownership_verified,
            "projected_assignment_fee": row.projected_assignment_fee,
            "reasons": row.reasons_json,
            "warnings": row.warnings_json,
        },
        "facts": [{
            "field_name": fact.field_name,
            "value": fact.value_json.get("value"),
            "source": fact.source,
            "confidence": fact.confidence,
            "verification_status": fact.verification_status,
            "observed_at": fact.observed_at,
        } for fact in facts],
    }

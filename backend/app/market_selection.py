"""Rank markets by wholesale criteria and cash-buyer activity.

Markets are keyed by ZIP, because that is what cash buyers actually declare
coverage in and what properties carry. Where a property has been verified,
county geography is attached so ZIPs can be rolled up to the county a
jurisdiction feed is configured against.

The scoring rule that matters: **missing evidence is not a zero.** A market
nobody has buyers in and a market nobody has looked at are different facts, and
collapsing them would rank an unexamined market as though it had been examined
and found wanting. Each dimension therefore reports whether it had evidence,
the composite is computed only across dimensions that did, and the response
states which were unavailable and why. A market scored on one dimension is
labelled as such rather than presented alongside a fully-evidenced one.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import WorkspaceEntity
from .database import get_db
from .distress_providers import EXCLUDED_STATES, PROVIDERS_BY_ID
from .intelligence_models import IntelligenceFact
from .models import Buyer, Deal, Lead, Property

router = APIRouter(prefix="/market-selection", tags=["market selection"])

# Weights are defaults; a caller may override them per request. They encode the
# ordering that decides whether a pipeline works: without an end buyer an
# assignment has nowhere to go, so buyer depth leads.
DEFAULT_WEIGHTS: dict[str, float] = {
    "cash_buyer_depth": 0.30,
    "buyer_liquidity": 0.15,
    "buy_box_fit": 0.15,
    "distress_supply": 0.25,
    "verified_coverage": 0.15,
}

DIMENSIONS: dict[str, str] = {
    "cash_buyer_depth": "Number and quality of cash buyers covering the market, weighted by verified proof of funds and reliability.",
    "buyer_liquidity": "How quickly and dependably those buyers transact, from closing speed and response rate.",
    "buy_box_fit": "Overlap between buyer price ranges and the market's observed property prices.",
    "distress_supply": "Verified distress records in the market from configured county feeds.",
    "verified_coverage": "Share of the market's properties verified against an authoritative geocoder.",
}

DIMENSION_REQUIREMENTS: dict[str, str] = {
    "cash_buyer_depth": "Buyer records with zip_codes coverage.",
    "buyer_liquidity": "Buyer records with closing_days and response_rate.",
    "buy_box_fit": "Properties with an asking price or ARV in the market.",
    "distress_supply": "A configured jurisdiction feed writing distress facts.",
    "verified_coverage": "Verified geography facts from /verified-ingest.",
}

DISTRESS_SOURCES = {
    provider_id for provider_id, spec in PROVIDERS_BY_ID.items()
    if spec.access == "public_record"
}


def _scoped_ids(db: Session, organization_id: int, entity_type: str) -> set[int]:
    return set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _zip5(value: Any) -> str:
    return str(value or "").strip()[:5]


def _collect(db: Session, organization_id: int) -> dict[str, dict[str, Any]]:
    """Build a per-ZIP view of buyers, properties, distress and verification."""
    markets: dict[str, dict[str, Any]] = {}

    def market(zip_code: str) -> dict[str, Any]:
        return markets.setdefault(zip_code, {
            "zip_code": zip_code, "buyers": [], "properties": [],
            "distress_facts": 0, "verified_properties": 0,
            "states": set(), "cities": set(), "counties": set(), "assignment_fees": [],
        })

    buyer_ids = _scoped_ids(db, organization_id, "buyer")
    if buyer_ids:
        for buyer in db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all():
            for raw in (buyer.zip_codes or []):
                code = _zip5(raw)
                if code:
                    market(code)["buyers"].append(buyer)

    property_ids = _scoped_ids(db, organization_id, "property")
    if property_ids:
        properties = db.scalars(select(Property).where(Property.id.in_(property_ids))).all()
        facts = db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_type == "property",
            IntelligenceFact.entity_id.in_([p.id for p in properties]),
        )).all() if properties else []

        by_property: dict[int, list[IntelligenceFact]] = {}
        for fact in facts:
            by_property.setdefault(fact.entity_id, []).append(fact)

        deals = {d.property_id: d for d in db.scalars(
            select(Deal).where(Deal.property_id.in_([p.id for p in properties]))
        ).all()} if properties else {}

        for prop in properties:
            state = (prop.state or "").upper()
            if state in EXCLUDED_STATES:
                continue
            entry = market(_zip5(prop.zip_code))
            entry["properties"].append(prop)
            entry["states"].add(state)
            if prop.city:
                entry["cities"].add(prop.city)

            rows = by_property.get(prop.id, [])
            if any(r.field_name == "county_name" for r in rows):
                entry["counties"].add(next(
                    (r.value_json or {}).get("value") for r in rows if r.field_name == "county_name"
                ))
            verified = {r.field_name for r in rows if r.verification_status == "verified"}
            if {"latitude", "longitude"} <= verified and prop.latitude is not None:
                entry["verified_properties"] += 1
            entry["distress_facts"] += sum(1 for r in rows if r.source in DISTRESS_SOURCES)

            deal = deals.get(prop.id)
            if deal and deal.projected_assignment_fee:
                entry["assignment_fees"].append(deal.projected_assignment_fee)

    return markets


def _score_market(entry: dict[str, Any]) -> dict[str, Any]:
    """Score one market, recording which dimensions had evidence."""
    scores: dict[str, float] = {}
    evidence: dict[str, bool] = {key: False for key in DIMENSIONS}
    buyers = entry["buyers"]
    properties = entry["properties"]

    if buyers:
        evidence["cash_buyer_depth"] = True
        # Depth saturates: the tenth buyer in a ZIP adds less than the second.
        count_component = min(len(buyers), 10) / 10 * 60
        quality = sum(
            (20 if b.proof_of_funds_verified else 0) + (b.reliability_score or 0) * 0.2
            for b in buyers
        ) / len(buyers)
        scores["cash_buyer_depth"] = _clamp(count_component + quality)

        evidence["buyer_liquidity"] = True
        closing = median([b.closing_days or 30 for b in buyers])
        response = sum(b.response_rate or 0 for b in buyers) / len(buyers)
        # 7-day close is excellent, 45+ is slow.
        speed = max(0.0, min(1.0, (45 - closing) / 38)) * 100
        scores["buyer_liquidity"] = _clamp(speed * 0.6 + response * 0.4)

    priced = [p for p in properties if (p.asking_price or p.arv)]
    if buyers and priced:
        evidence["buy_box_fit"] = True
        fits = 0
        for prop in priced:
            price = prop.asking_price or prop.arv or 0
            rehab = prop.repairs or 0
            if any(b.min_price <= price <= b.max_price and rehab <= b.max_rehab for b in buyers):
                fits += 1
        scores["buy_box_fit"] = _clamp(fits / len(priced) * 100)

    if entry["distress_facts"]:
        evidence["distress_supply"] = True
        # Ten distress signals in a ZIP is a strong supply indication.
        scores["distress_supply"] = _clamp(min(entry["distress_facts"], 10) / 10 * 100)

    if properties:
        evidence["verified_coverage"] = True
        scores["verified_coverage"] = _clamp(entry["verified_properties"] / len(properties) * 100)

    return {"scores": scores, "evidence": evidence}


def _composite(scores: dict[str, float], weights: dict[str, float]) -> tuple[float | None, float]:
    """Weighted mean over evidenced dimensions only, plus the weight covered."""
    covered = {key: weights[key] for key in scores if key in weights}
    total = sum(covered.values())
    if not total:
        return None, 0.0
    value = sum(scores[key] * weight for key, weight in covered.items()) / total
    return round(value, 1), round(total / sum(weights.values()) * 100, 1)


def _confidence(coverage_percent: float) -> str:
    if coverage_percent >= 80:
        return "high"
    if coverage_percent >= 50:
        return "moderate"
    if coverage_percent > 0:
        return "low"
    return "none"


@router.get("/criteria")
def criteria(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "market_key": "zip_code",
        "dimensions": [{
            "id": key,
            "description": DIMENSIONS[key],
            "requires": DIMENSION_REQUIREMENTS[key],
            "default_weight": DEFAULT_WEIGHTS[key],
        } for key in DIMENSIONS],
        "excluded_states": sorted(EXCLUDED_STATES),
        "scoring_rule": (
            "Missing evidence is not scored as zero. The composite is a weighted mean over dimensions "
            "that had evidence, and every market reports which dimensions were unavailable."
        ),
    }


@router.post("/rank")
def rank(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (payload.get("weights") or {}).items():
        if key not in DEFAULT_WEIGHTS:
            raise HTTPException(422, f"Unknown weight '{key}'. Valid: {', '.join(DEFAULT_WEIGHTS)}")
        weights[key] = float(value)
    if sum(weights.values()) <= 0:
        raise HTTPException(422, "Weights must sum to more than zero")

    states = {str(s).strip().upper() for s in (payload.get("states") or []) if str(s).strip()}
    min_buyers = int(payload.get("min_cash_buyers") or 0)
    min_confidence = str(payload.get("min_confidence") or "none").lower()
    limit = min(int(payload.get("limit") or 50), 500)

    markets = _collect(db, principal.organization_id)
    ranked, unscored = [], []
    for entry in markets.values():
        if states and not (entry["states"] & states):
            continue
        if len(entry["buyers"]) < min_buyers:
            continue

        result = _score_market(entry)
        composite, coverage = _composite(result["scores"], weights)
        confidence = _confidence(coverage)
        row = {
            "zip_code": entry["zip_code"],
            "states": sorted(entry["states"]),
            "cities": sorted(c for c in entry["cities"] if c),
            "counties": sorted(c for c in entry["counties"] if c),
            "composite_score": composite,
            "evidence_coverage_percent": coverage,
            "confidence": confidence,
            "scores": result["scores"],
            "missing_dimensions": [
                {"id": key, "requires": DIMENSION_REQUIREMENTS[key]}
                for key, present in result["evidence"].items() if not present
            ],
            "cash_buyers": len(entry["buyers"]),
            "verified_properties": entry["verified_properties"],
            "properties": len(entry["properties"]),
            "distress_facts": entry["distress_facts"],
            "median_assignment_fee": (
                round(median(entry["assignment_fees"]), 2) if entry["assignment_fees"] else None
            ),
        }
        (unscored if composite is None else ranked).append(row)

    order = {"none": 0, "low": 1, "moderate": 2, "high": 3}
    if min_confidence in order:
        ranked = [r for r in ranked if order[r["confidence"]] >= order[min_confidence]]
    ranked.sort(key=lambda r: (r["composite_score"], r["evidence_coverage_percent"]), reverse=True)

    return {
        "organization_id": principal.organization_id,
        "weights": weights,
        "filters": {
            "states": sorted(states), "min_cash_buyers": min_buyers,
            "min_confidence": min_confidence, "limit": limit,
        },
        "summary": {
            "markets_considered": len(markets),
            "ranked": len(ranked),
            "unscorable": len(unscored),
            "high_confidence": sum(1 for r in ranked if r["confidence"] == "high"),
        },
        "markets": ranked[:limit],
        # Kept separate so an unexamined market is never presented as a poor one.
        "unscorable_markets": [
            {"zip_code": r["zip_code"], "states": r["states"], "reason": "No evidence on any scored dimension"}
            for r in unscored[:limit]
        ],
        "note": (
            "Scores reflect this workspace's own buyer, property and verified-record data. "
            "A market with no buyers on file scores low on depth because none are recorded, "
            "which is a statement about your data, not about the market."
        ),
    }


@router.get("/market/{zip_code}")
def market_detail(
    zip_code: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    entry = _collect(db, principal.organization_id).get(_zip5(zip_code))
    if not entry:
        raise HTTPException(404, f"No workspace data for market {zip_code}")
    result = _score_market(entry)
    composite, coverage = _composite(result["scores"], DEFAULT_WEIGHTS)
    return {
        "organization_id": principal.organization_id,
        "zip_code": entry["zip_code"],
        "states": sorted(entry["states"]),
        "cities": sorted(c for c in entry["cities"] if c),
        "counties": sorted(c for c in entry["counties"] if c),
        "composite_score": composite,
        "evidence_coverage_percent": coverage,
        "confidence": _confidence(coverage),
        "scores": result["scores"],
        "missing_dimensions": [
            {"id": key, "requires": DIMENSION_REQUIREMENTS[key]}
            for key, present in result["evidence"].items() if not present
        ],
        "cash_buyers": [{
            "name": b.name,
            "company": b.company,
            "buyer_type": b.buyer_type,
            "proof_of_funds_verified": b.proof_of_funds_verified,
            "closing_days": b.closing_days,
            "response_rate": b.response_rate,
            "reliability_score": b.reliability_score,
            "price_band": [b.min_price, b.max_price],
        } for b in entry["buyers"]],
        "properties": len(entry["properties"]),
        "verified_properties": entry["verified_properties"],
        "distress_facts": entry["distress_facts"],
    }

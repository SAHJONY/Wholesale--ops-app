"""Tenant-scoped API surface for the decision-intelligence engines.

Composes :mod:`valuation`, :mod:`adaptive_scoring`, :mod:`buyer_intelligence`,
:mod:`pipeline_forecast`, and :mod:`decision_intelligence` into endpoints the
operations console consumes. Every route is scoped to the caller's workspace
through ``WorkspaceEntity``, matching the tenancy model the rest of the API
already enforces.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import (
    adaptive_scoring,
    buyer_intelligence,
    decision_intelligence,
    flood_risk,
    market_data,
    pipeline_forecast,
)
from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Approval, Buyer, Deal, Lead, Property
from .valuation import (
    DEFAULT_MONTHLY_APPRECIATION,
    Comparable,
    SubjectProperty,
    ValuationError,
    _decision_quality,
    simulate_deal,
    underwrite,
)

router = APIRouter(prefix="/deal-intelligence", tags=["decision intelligence"])

ACTIVE_STAGES_EXCLUDED = {"closed", "dead"}


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(
        db.scalars(
            select(WorkspaceEntity.entity_id).where(
                WorkspaceEntity.organization_id == organization_id,
                WorkspaceEntity.entity_type == entity_type,
            )
        ).all()
    )


def _org_leads(db: Session, principal: Principal) -> list[Lead]:
    ids = _linked_ids(db, principal.organization_id, "lead")
    if not ids:
        return []
    return list(db.scalars(select(Lead).where(Lead.id.in_(ids))).all())


def _org_buyers(db: Session, principal: Principal) -> list[Buyer]:
    ids = _linked_ids(db, principal.organization_id, "buyer")
    if not ids:
        return []
    return list(db.scalars(select(Buyer).where(Buyer.id.in_(ids))).all())


def _org_deals(db: Session, principal: Principal) -> list[Deal]:
    ids = _linked_ids(db, principal.organization_id, "deal")
    if not ids:
        return []
    return list(db.scalars(select(Deal).where(Deal.id.in_(ids))).all())


def _buyer_dict(buyer: Buyer) -> dict:
    return {
        "id": buyer.id,
        "name": buyer.name,
        "zip_codes": buyer.zip_codes or [],
        "asset_types": buyer.asset_types or [],
        "min_price": buyer.min_price,
        "max_price": buyer.max_price,
        "max_rehab": buyer.max_rehab,
        "closing_days": buyer.closing_days,
        "proof_of_funds_verified": buyer.proof_of_funds_verified,
        "response_rate": buyer.response_rate,
        "reliability_score": buyer.reliability_score,
    }


def _property_dict(prop: Property | None) -> dict:
    if prop is None:
        return {}
    return {
        "id": prop.id,
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
        "mao": prop.mao,
        "distress_signals": prop.distress_signals or [],
    }


def _buyer_demand_score(prop: Property | None, buyers: list[dict]) -> float:
    """Live buyer demand for a property, as the mean of the top three fits.

    The legacy scorer hardcoded 50 for buyer demand. This measures it against
    the workspace's actual buyer list, so a property in a ZIP nobody buys in
    scores lower than one three cash buyers are competing for.
    """
    if prop is None or not buyers:
        return 50.0
    ranked = buyer_intelligence.rank_buyers(_property_dict(prop), buyers)
    if not ranked:
        return 0.0
    top = [row["response_probability"] for row in ranked[:3]]
    return round(100.0 * sum(top) / len(top), 2)


def _lead_record(lead: Lead, buyers: list[dict]) -> dict:
    prop = lead.property
    age_days = None
    if lead.created_at:
        created = lead.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0)

    return {
        "id": lead.id,
        "seller_name": lead.seller_name,
        "phone": lead.phone,
        "email": lead.email,
        "status": lead.status,
        "motivation_score": lead.motivation_score,
        "equity_score": lead.equity_score,
        "distress_score": lead.distress_score,
        "buyer_demand_score": _buyer_demand_score(prop, buyers),
        "timeline_days": lead.timeline_days,
        "age_days": age_days,
        "arv": prop.arv if prop else None,
        "asking_price": prop.asking_price if prop else None,
        "address": prop.address if prop else None,
        "zip_code": prop.zip_code if prop else None,
    }


def _training_rows(db: Session, principal: Principal, buyers: list[dict]) -> list[tuple[dict, int]]:
    """Build supervised training data from resolved deals.

    Only deals that reached a terminal stage are included. Open deals carry no
    label — treating them as negatives would teach the model to predict "has
    not closed yet" rather than "will not close".
    """
    rows: list[tuple[dict, int]] = []
    for deal in _org_deals(db, principal):
        stage = str(deal.stage or "").strip().lower()
        if stage not in ACTIVE_STAGES_EXCLUDED:
            continue
        prop = db.get(Property, deal.property_id)
        if not prop:
            continue
        lead = db.get(Lead, prop.lead_id)
        if not lead:
            continue
        rows.append((_lead_record(lead, buyers), 1 if stage == "closed" else 0))
    return rows


def _fit_model(db: Session, principal: Principal, buyers: list[dict]):
    return adaptive_scoring.fit(_training_rows(db, principal, buyers))


def _resolve_market(zip_code: str | None, state: str | None) -> dict:
    """Resolve free public market data for a location.

    Market data is advisory: a Census or FHFA outage must degrade the
    underwriting record, never fail it. Every branch records whether the
    appreciation rate is measured or assumed.
    """
    market: dict = {"zip_code": zip_code, "state": state, "errors": []}

    appreciation = None
    if zip_code or state:
        try:
            appreciation = market_data.fetch_appreciation(zip_code=zip_code, state=state)
        except Exception as exc:  # noqa: BLE001 - advisory data must not fail underwriting
            market["errors"].append(f"appreciation: {type(exc).__name__}: {exc}")

    if appreciation is None:
        market["appreciation"] = {
            "monthly_rate": DEFAULT_MONTHLY_APPRECIATION,
            "measured": False,
            "level": "fallback",
            "note": "No location supplied or no index reachable; using the built-in constant.",
        }
    else:
        market["appreciation"] = appreciation.as_dict()

    if zip_code:
        try:
            context = market_data.fetch_market_context(zip_code)
            market["context"] = context.as_dict()
            market["_context_object"] = context
        except Exception as exc:  # noqa: BLE001
            market["errors"].append(f"context: {type(exc).__name__}: {exc}")

    return market


@router.get("/status")
def status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Report which intelligence capabilities are live for this workspace."""
    buyers = [_buyer_dict(buyer) for buyer in _org_buyers(db, principal)]
    model = _fit_model(db, principal, buyers)
    return {
        "generated_at": datetime.now(timezone.utc),
        "reasoning_model": {
            "configured": decision_intelligence.is_configured(),
            "engine": "claude" if decision_intelligence.is_configured() else "deterministic",
            "note": (
                "Structured reasoning is live."
                if decision_intelligence.is_configured()
                else "ANTHROPIC_API_KEY is not set; analyses fall back to deterministic rules."
            ),
        },
        "scoring_model": model.as_dict(),
        "buyers_available": len(buyers),
        "capabilities": {
            "comparable_sales_valuation": True,
            "monte_carlo_underwriting": True,
            "adaptive_lead_scoring": True,
            "portfolio_disposition": bool(buyers),
            "pipeline_forecasting": True,
            "public_market_data": True,
            "flood_risk_screening": True,
        },
        "public_data_sources": market_data.source_registry() + flood_risk.source_registry(),
        "data_gaps": [
            {
                "gap": "individual comparable sales",
                "detail": (
                    "No free national source of arms-length sale prices exists. Comparables "
                    "must come from a licensed provider or a county-level open data feed; "
                    "roughly a dozen states are non-disclosure and publish no sale price at all."
                ),
            }
        ],
    }


@router.post("/underwrite")
def underwrite_property(
    payload: dict,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    """Underwrite a property from comparable sales and simulate the outcome.

    Comparables must be supplied by the caller from a licensed or public data
    source. None are inferred: an invented comparable would corrupt every
    number downstream of it.
    """
    subject_payload = payload.get("subject") or {}
    comps_payload = payload.get("comparables") or []
    if not comps_payload:
        raise HTTPException(422, "At least one comparable sale is required")

    try:
        subject = SubjectProperty(
            sqft=int(subject_payload.get("sqft") or 0),
            bedrooms=subject_payload.get("bedrooms"),
            bathrooms=subject_payload.get("bathrooms"),
            year_built=subject_payload.get("year_built"),
            condition=str(subject_payload.get("condition") or "moderate"),
            distress_signals=tuple(subject_payload.get("distress_signals") or []),
        )
        comparables = [
            Comparable(
                address=str(item.get("address") or "unspecified"),
                sale_price=float(item["sale_price"]),
                sale_date=date.fromisoformat(str(item["sale_date"])),
                sqft=int(item["sqft"]),
                bedrooms=item.get("bedrooms"),
                bathrooms=item.get("bathrooms"),
                year_built=item.get("year_built"),
                distance_miles=float(item.get("distance_miles") or 0.0),
                condition=str(item.get("condition") or "average"),
                source=str(item.get("source") or "unspecified"),
            )
            for item in comps_payload
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid comparable or subject data: {exc}") from exc

    # Free public market data: measured FHFA appreciation drives the
    # comparable time adjustment, and the Census median screens the result.
    market = _resolve_market(
        str(subject_payload.get("zip_code") or "").strip() or None,
        str(subject_payload.get("state") or "").strip() or None,
    )
    context = market.pop("_context_object", None)

    try:
        result = underwrite(
            subject,
            comparables,
            contract_price=payload.get("contract_price"),
            target_fee=float(payload.get("target_fee") or 15_000),
            repairs_override=payload.get("repairs"),
            confidence_target=float(payload.get("confidence_target") or 0.75),
            monthly_appreciation=float(market["appreciation"]["monthly_rate"]),
            appreciation_provenance=market["appreciation"],
        )
    except ValuationError as exc:
        raise HTTPException(422, str(exc)) from exc

    if context is not None:
        market["plausibility"] = market_data.check_arv_plausibility(
            result["valuation"]["arv"], context
        )
        verdict = market["plausibility"].get("verdict")
        if verdict in {"implausible_high", "implausible_low"}:
            result["valuation"]["warnings"].append(market["plausibility"]["guidance"])
    result["market"] = market

    # FEMA flood risk. This is reported rather than silently deducted, because
    # the comparables may already price the flood zone in: if they sit in the
    # same SFHA as the subject, the discount is embedded in the derived ARV and
    # subtracting it again would double-count. The adjustment is therefore
    # opt-in, for the case where the operator knows the comparables are not
    # zone-matched.
    flood = _resolve_flood(subject_payload)
    zone = flood.pop("_zone_object", None)
    loss_history = flood.pop("_loss_history", None)

    if zone is not None:
        assessment = flood_risk.assess_flood_risk(
            zone, arv=result["valuation"]["arv"], loss_history=loss_history
        )
        flood["assessment"] = assessment
        result["valuation"]["warnings"].extend(assessment["warnings"])

        if zone.in_sfha:
            flood["comparable_guidance"] = (
                "Subject is in a Special Flood Hazard Area. Confirm the comparables are "
                "similarly zoned — if they are not, the derived ARV does not reflect the "
                "flood discount and should be adjusted."
            )

        if payload.get("apply_flood_adjustment") and assessment["capitalized_value_impact"] > 0:
            adjusted_arv = max(0.0, result["valuation"]["arv"] - assessment["capitalized_value_impact"])
            simulation = simulate_deal(
                arv=adjusted_arv,
                arv_low=max(0.0, result["valuation"]["confidence_interval"]["low"] - assessment["capitalized_value_impact"]),
                arv_high=max(0.0, result["valuation"]["confidence_interval"]["high"] - assessment["capitalized_value_impact"]),
                repairs=result["repairs_used"],
                contract_price=result["evaluated_contract_price"],
                target_fee=float(payload.get("target_fee") or 15_000),
                confidence_target=float(payload.get("confidence_target") or 0.75),
            )
            flood["adjustment_applied"] = {
                "unadjusted_arv": result["valuation"]["arv"],
                "adjusted_arv": round(adjusted_arv, 2),
                "deducted": assessment["capitalized_value_impact"],
                "note": "Applied at the caller's request; verify the comparables are not already zone-matched.",
            }
            result["simulation"] = simulation.as_dict()
            result["recommended_max_offer"] = round(simulation.recommended_max_offer, 2)
            result["decision_quality"] = _decision_quality(
                result["valuation"]["confidence"], simulation.probability_of_target
            )
    result["flood"] = flood

    if payload.get("include_analysis", True):
        result["analysis"] = decision_intelligence.analyze(
            "deal_review",
            {
                "underwriting": result,
                "property": subject_payload,
                "market": payload.get("market"),
                "flood_risk": result.get("flood", {}).get("assessment"),
            },
        )

    db.add(
        CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            activity_type="deal_underwritten",
            summary=(
                f"Underwrote {subject_payload.get('address', 'a property')} at "
                f"${result['valuation']['arv']:,.0f} ARV "
                f"({result['decision_quality']['verdict']})"
            ),
            metadata_json={
                "arv": result["valuation"]["arv"],
                "recommended_max_offer": result["recommended_max_offer"],
                "verdict": result["decision_quality"]["verdict"],
                "comparables_supplied": len(comparables),
            },
        )
    )
    db.commit()
    return result


def _resolve_flood(subject: dict) -> dict:
    """Resolve FEMA flood risk for a subject property.

    Accepts explicit coordinates, or geocodes the address through the free
    Census geocoder. Like market data this is advisory: a FEMA outage degrades
    the record rather than failing the underwriting.
    """
    result: dict = {"errors": []}

    latitude, longitude = subject.get("latitude"), subject.get("longitude")
    if latitude is None or longitude is None:
        address_parts = [
            str(subject.get(key) or "").strip()
            for key in ("address", "city", "state", "zip_code")
        ]
        address = ", ".join(part for part in address_parts if part)
        if not address:
            result["errors"].append("No coordinates or address supplied for a flood lookup")
            return result
        try:
            geocode = flood_risk.geocode_address(address)
            latitude, longitude = geocode.latitude, geocode.longitude
            result["geocode"] = geocode.as_dict()
        except Exception as exc:  # noqa: BLE001 - advisory data must not fail underwriting
            result["errors"].append(f"geocode: {type(exc).__name__}: {exc}")
            return result

    try:
        zone = flood_risk.lookup_flood_zone(float(latitude), float(longitude))
        result["zone"] = zone.as_dict()
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"flood_zone: {type(exc).__name__}: {exc}")
        return result

    loss_history = None
    zip_code = str(subject.get("zip_code") or "").strip()
    if zip_code:
        try:
            loss_history = flood_risk.fetch_flood_loss_history(zip_code)
            result["loss_history"] = loss_history.as_dict()
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"loss_history: {type(exc).__name__}: {exc}")

    result["_zone_object"] = zone
    result["_loss_history"] = loss_history
    return result


@router.get("/flood")
def flood(
    address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    zip_code: str | None = None,
    principal: Principal = Depends(get_principal),
):
    """FEMA flood zone and realized flood losses for an address or coordinate.

    Free, no API key: FEMA National Flood Hazard Layer for the zone, the Census
    geocoder to resolve an address, and OpenFEMA for actual NFIP claims and
    premiums in the ZIP.
    """
    if address is None and (latitude is None or longitude is None):
        raise HTTPException(422, "Supply either an address or both latitude and longitude")

    subject = {
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "zip_code": zip_code,
    }
    resolved = _resolve_flood(subject)
    zone = resolved.pop("_zone_object", None)
    loss_history = resolved.pop("_loss_history", None)

    if zone is None:
        resolved["status"] = "degraded"
        resolved["detail"] = (
            "FEMA flood data could not be retrieved. Check outbound network access to "
            "hazards.fema.gov, geocoding.geo.census.gov, and www.fema.gov."
        )
    else:
        resolved["status"] = "ok"
        resolved["assessment"] = flood_risk.assess_flood_risk(zone, loss_history=loss_history)

    resolved["sources"] = flood_risk.source_registry()
    return resolved


@router.get("/market/{zip_code}")
def market(zip_code: str, state: str | None = None, principal: Principal = Depends(get_principal)):
    """Free public market data for a ZIP: Census ACS context and FHFA appreciation.

    Both sources are U.S. Government works requiring no API key. Neither
    contains individual sales — see `docs/FREE_DATA_SOURCES.md` for what this
    can and cannot substitute for.
    """
    zip_code = str(zip_code).strip()
    if not (len(zip_code) == 5 and zip_code.isdigit()):
        raise HTTPException(422, "Expected a five-digit ZIP code")

    resolved = _resolve_market(zip_code, state)
    resolved.pop("_context_object", None)
    resolved["sources"] = market_data.source_registry()

    if resolved["errors"] and "context" not in resolved:
        # Be explicit that this is an availability problem, not an empty market.
        resolved["status"] = "degraded"
        resolved["detail"] = (
            "Public market data could not be retrieved. Check outbound network access to "
            "api.census.gov and www.fhfa.gov from this deployment."
        )
    else:
        resolved["status"] = "ok"
    return resolved


@router.get("/leads/ranked")
def ranked_leads(
    limit: int = 50,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Rank workspace leads by calibrated conversion probability."""
    limit = max(1, min(500, limit))
    buyers = [_buyer_dict(buyer) for buyer in _org_buyers(db, principal)]
    model = _fit_model(db, principal, buyers)
    records = [_lead_record(lead, buyers) for lead in _org_leads(db, principal)]
    ranked = adaptive_scoring.rank(records, model)

    by_id = {record["id"]: record for record in records}
    for row in ranked:
        record = by_id.get(row["lead_id"], {})
        row["seller_name"] = record.get("seller_name")
        row["address"] = record.get("address")
        row["status"] = record.get("status")

    return {
        "generated_at": datetime.now(timezone.utc),
        "model": model.as_dict(),
        "lead_count": len(ranked),
        "leads": ranked[:limit],
    }


@router.get("/leads/{lead_id}/call-brief")
def call_brief(
    lead_id: int,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    """Prepare a structured acquisitions call brief for one seller lead."""
    if lead_id not in set(_linked_ids(db, principal.organization_id, "lead")):
        raise HTTPException(404, "Lead not found in this workspace")
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")

    buyers = [_buyer_dict(buyer) for buyer in _org_buyers(db, principal)]
    record = _lead_record(lead, buyers)
    model = _fit_model(db, principal, buyers)

    return {
        "lead_id": lead_id,
        "scoring": adaptive_scoring.score(record, model),
        "brief": decision_intelligence.analyze(
            "seller_brief", {"lead": record, "property": _property_dict(lead.property)}
        ),
        "compliance_reminder": (
            "Confirm consent, DNC status, and quiet hours before dialing. Nothing in this "
            "brief authorizes an offer, a price commitment, or a claim about funds."
        ),
    }


@router.get("/forecast")
def pipeline(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Probability-weighted revenue forecast for the open pipeline."""
    deals = _org_deals(db, principal)
    open_deals = [
        {
            "id": deal.id,
            "stage": deal.stage,
            "projected_assignment_fee": deal.projected_assignment_fee,
            "updated_at": deal.updated_at,
        }
        for deal in deals
        if str(deal.stage or "").lower() not in ACTIVE_STAGES_EXCLUDED
    ]
    history = [
        {
            "furthest_stage": (deal.metadata_json or {}).get("furthest_stage") or deal.stage,
            "outcome": str(deal.stage or "").lower(),
        }
        for deal in deals
        if str(deal.stage or "").lower() in ACTIVE_STAGES_EXCLUDED
    ]
    return pipeline_forecast.forecast(open_deals, history)


@router.post("/disposition/plan")
def disposition_plan(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("disposition")),
    db: Session = Depends(get_db),
):
    """Assign buyers across the open pipeline to maximise expected revenue."""
    options = payload or {}
    buyers = [_buyer_dict(buyer) for buyer in _org_buyers(db, principal)]
    if not buyers:
        raise HTTPException(422, "No buyers are linked to this workspace")

    deals = []
    for deal in _org_deals(db, principal):
        if str(deal.stage or "").lower() in ACTIVE_STAGES_EXCLUDED:
            continue
        prop = db.get(Property, deal.property_id)
        deals.append(
            {
                "id": deal.id,
                "projected_assignment_fee": deal.projected_assignment_fee,
                "property": _property_dict(prop),
            }
        )
    if not deals:
        raise HTTPException(422, "No open deals are available to plan against")

    plan = buyer_intelligence.optimize_assignments(
        deals,
        buyers,
        buyer_capacity=int(options.get("buyer_capacity") or buyer_intelligence.DEFAULT_BUYER_CAPACITY),
        offers_per_deal=int(options.get("offers_per_deal") or 1),
        minimum_probability=float(options.get("minimum_probability") or 0.05),
    )
    plan["approval_required"] = True
    plan["approval_note"] = (
        "This is a proposed outreach plan. Launching it to buyers requires an approved "
        "campaign through the existing approval gate."
    )
    return plan


@router.get("/briefing")
def briefing(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Executive briefing combining the forecast with ranked priorities."""
    buyers = [_buyer_dict(buyer) for buyer in _org_buyers(db, principal)]
    model = _fit_model(db, principal, buyers)
    leads = _org_leads(db, principal)
    records = [_lead_record(lead, buyers) for lead in leads]
    ranked = adaptive_scoring.rank(records, model)

    deals = _org_deals(db, principal)
    open_deals = [
        {
            "id": deal.id,
            "stage": deal.stage,
            "projected_assignment_fee": deal.projected_assignment_fee,
            "updated_at": deal.updated_at,
        }
        for deal in deals
        if str(deal.stage or "").lower() not in ACTIVE_STAGES_EXCLUDED
    ]
    history = [
        {
            "furthest_stage": (deal.metadata_json or {}).get("furthest_stage") or deal.stage,
            "outcome": str(deal.stage or "").lower(),
        }
        for deal in deals
        if str(deal.stage or "").lower() in ACTIVE_STAGES_EXCLUDED
    ]
    projection = pipeline_forecast.forecast(open_deals, history)

    approval_ids = _linked_ids(db, principal.organization_id, "approval")
    pending_approvals = (
        len(
            db.scalars(
                select(Approval).where(
                    Approval.id.in_(approval_ids), Approval.status == "pending"
                )
            ).all()
        )
        if approval_ids
        else 0
    )

    priority_leads = [row for row in ranked if row["band"] == "priority"]
    analysis = decision_intelligence.analyze(
        "portfolio_priorities",
        {
            "pending_approvals": pending_approvals,
            "hot_leads": len(priority_leads),
            "active_deals": len(open_deals),
            "stalled_deals": len(projection["stalled_deals"]),
            "expected_revenue": projection["expected_revenue"],
            "nominal_pipeline_value": projection["nominal_pipeline_value"],
            "bottlenecks": projection["bottlenecks"][:3],
        },
    )

    return {
        "generated_at": datetime.now(timezone.utc),
        "analysis": analysis,
        "forecast": {
            "expected_revenue": projection["expected_revenue"],
            "nominal_pipeline_value": projection["nominal_pipeline_value"],
            "revenue_interval": projection["revenue_interval"],
            "overstatement_vs_nominal": projection["overstatement_vs_nominal"],
            "bottlenecks": projection["bottlenecks"],
            "stalled_deals": projection["stalled_deals"],
        },
        "leads": {
            "total": len(ranked),
            "priority": len(priority_leads),
            "top": ranked[:10],
        },
        "pending_approvals": pending_approvals,
        "scoring_model": model.as_dict(),
    }

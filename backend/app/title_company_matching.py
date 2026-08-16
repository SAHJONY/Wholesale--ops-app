from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .closing_command_models import TitleOrder
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .models import Deal, Property
from .title_company_models import TitleCompanyDealMatch, TitleCompanyPartner

router = APIRouter(prefix="/title-company-matching", tags=["title company matching"])

CAPABILITY_VALUES = {"verified", "claimed", "unverified", "unsupported"}
CAPABILITY_FIELDS = {
    "assignment": "assignment_support",
    "assignment_contract": "assignment_support",
    "double_close": "double_close_support",
    "double_closing": "double_close_support",
    "simultaneous_close": "simultaneous_close_support",
}
TERMINAL_DEAL_STAGES = {"closed", "dead", "cancelled"}


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _norm_geo(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _capability_status(value: Any) -> str:
    status = str(value or "unverified").strip().lower()
    if status not in CAPABILITY_VALUES:
        raise HTTPException(422, f"Capability status must be one of {sorted(CAPABILITY_VALUES)}")
    return status


def _serialize_partner(row: TitleCompanyPartner) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "website": row.website,
        "phone": row.phone,
        "email": row.email,
        "states": row.states or [],
        "counties": row.counties or [],
        "zip_codes": row.zip_codes or [],
        "active": bool(row.active),
        "capabilities": {
            "assignment": row.assignment_support,
            "double_close": row.double_close_support,
            "simultaneous_close": row.simultaneous_close_support,
            "transactional_funding_coordination": row.transactional_funding_coordination,
            "remote_closing": row.remote_closing,
            "e_signing": row.e_signing,
        },
        "track_record": {
            "investor_closings_observed": row.investor_closings_observed,
            "wholesale_closings_observed": row.wholesale_closings_observed,
            "avg_title_turnaround_days": row.avg_title_turnaround_days,
            "avg_closing_days": row.avg_closing_days,
            "reliability_score": row.reliability_score,
            "fee_transparency_score": row.fee_transparency_score,
        },
        "underwriter": row.underwriter,
        "license_reference": row.license_reference,
        "evidence": row.evidence or [],
        "notes": row.notes,
        "last_verified_at": row.last_verified_at,
    }


def _deal_context(db: Session, principal: Principal, deal_id: int) -> tuple[Deal, Property]:
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    if not prop:
        raise HTTPException(422, "Deal property is missing")
    return deal, prop


def _jurisdiction_fit(partner: TitleCompanyPartner, prop: Property, county: str | None) -> tuple[bool, float, list[str]]:
    reasons: list[str] = []
    states = {_norm_geo(x).upper() for x in (partner.states or []) if str(x).strip()}
    state = str(prop.state or "").strip().upper()
    if states and state not in states:
        return False, 0.0, ["state_not_supported"]
    score = 15.0
    reasons.append("state_supported")

    zips = {_norm_geo(x) for x in (partner.zip_codes or []) if str(x).strip()}
    counties = {_norm_geo(x) for x in (partner.counties or []) if str(x).strip()}
    if zips and _norm_geo(prop.zip_code) in zips:
        score += 10.0
        reasons.append("zip_supported")
    elif county and counties and _norm_geo(county) in counties:
        score += 10.0
        reasons.append("county_supported")
    elif not zips and not counties:
        score += 5.0
        reasons.append("statewide_or_unspecified_local_coverage")
    else:
        reasons.append("local_coverage_not_explicitly_matched")
    return True, min(25.0, score), reasons


def _strategy_fit(partner: TitleCompanyPartner, strategy: str) -> tuple[bool, float, str, list[str]]:
    normalized = str(strategy or "assignment").strip().lower()
    capability_field = CAPABILITY_FIELDS.get(normalized)
    if capability_field is None:
        return True, 15.0, "general_closing", ["no_special_wholesale_capability_required_for_strategy"]
    status = str(getattr(partner, capability_field) or "unverified").lower()
    if status == "verified":
        return True, 30.0, "verified", [f"{normalized}_support_verified"]
    if status == "claimed":
        return False, 10.0, "needs_verification", [f"{normalized}_support_claimed_not_verified"]
    if status == "unsupported":
        return False, 0.0, "unsupported", [f"{normalized}_unsupported"]
    return False, 0.0, "needs_verification", [f"{normalized}_support_unverified"]


def score_title_company(
    partner: TitleCompanyPartner,
    prop: Property,
    strategy: str,
    *,
    county: str | None = None,
) -> dict[str, Any]:
    if not partner.active:
        return {"eligible": False, "score": 0.0, "evidence_status": "inactive", "reasons": ["partner_inactive"], "components": {}}

    geo_ok, geo_score, geo_reasons = _jurisdiction_fit(partner, prop, county)
    strategy_ok, strategy_score, evidence_status, strategy_reasons = _strategy_fit(partner, strategy)

    wholesale_count = max(0, int(partner.wholesale_closings_observed or 0))
    investor_count = max(0, int(partner.investor_closings_observed or 0))
    experience_score = min(15.0, wholesale_count * 1.5 + investor_count * 0.25)

    turnaround = partner.avg_title_turnaround_days
    if turnaround is None:
        turnaround_score = 4.0
    elif turnaround <= 2:
        turnaround_score = 10.0
    elif turnaround <= 4:
        turnaround_score = 8.0
    elif turnaround <= 7:
        turnaround_score = 5.0
    else:
        turnaround_score = 2.0

    reliability_score = min(10.0, max(0.0, float(partner.reliability_score or 0)) / 10.0)
    fee_score = min(5.0, max(0.0, float(partner.fee_transparency_score or 0)) / 20.0)
    digital_score = 0.0
    if str(partner.remote_closing or "") == "verified":
        digital_score += 3.0
    if str(partner.e_signing or "") == "verified":
        digital_score += 2.0

    score = round(min(100.0, geo_score + strategy_score + experience_score + turnaround_score + reliability_score + fee_score + digital_score), 2)
    eligible = bool(geo_ok and strategy_ok)
    reasons = geo_reasons + strategy_reasons
    if wholesale_count >= 5:
        reasons.append("repeat_wholesale_closing_history")
    if turnaround is not None and turnaround <= 4:
        reasons.append("fast_title_turnaround")
    if float(partner.reliability_score or 0) >= 80:
        reasons.append("high_reliability")

    return {
        "eligible": eligible,
        "score": score,
        "evidence_status": evidence_status if geo_ok else "jurisdiction_mismatch",
        "reasons": reasons,
        "components": {
            "jurisdiction_fit": round(geo_score, 2),
            "strategy_capability": round(strategy_score, 2),
            "wholesale_investor_experience": round(experience_score, 2),
            "title_turnaround": round(turnaround_score, 2),
            "reliability": round(reliability_score, 2),
            "fee_transparency": round(fee_score, 2),
            "digital_closing": round(digital_score, 2),
        },
    }


def _validate_verified_capabilities(payload: dict[str, Any], existing: TitleCompanyPartner | None = None) -> None:
    evidence = payload.get("evidence") if "evidence" in payload else (existing.evidence if existing else [])
    evidence = evidence or []
    capability_keys = [
        "assignment_support", "double_close_support", "simultaneous_close_support",
        "transactional_funding_coordination", "remote_closing", "e_signing",
    ]
    for key in capability_keys:
        if key in payload and _capability_status(payload[key]) == "verified" and not evidence:
            raise HTTPException(422, f"{key}=verified requires at least one evidence record")


def _upsert_match(
    db: Session,
    principal: Principal,
    deal_id: int,
    partner: TitleCompanyPartner,
    strategy: str,
    intelligence: dict[str, Any],
) -> TitleCompanyDealMatch:
    row = db.scalar(select(TitleCompanyDealMatch).where(
        TitleCompanyDealMatch.organization_id == principal.organization_id,
        TitleCompanyDealMatch.deal_id == deal_id,
        TitleCompanyDealMatch.title_company_id == partner.id,
    ))
    if row is None:
        row = TitleCompanyDealMatch(
            organization_id=principal.organization_id,
            deal_id=deal_id,
            title_company_id=partner.id,
        )
        db.add(row)
    row.requested_strategy = strategy
    row.score = float(intelligence["score"])
    row.eligible = bool(intelligence["eligible"])
    row.evidence_status = str(intelligence["evidence_status"])
    row.reasons = list(intelligence["reasons"])
    row.status = "recommended" if row.eligible and row.score >= 70 else "ranked" if row.eligible else "needs_verification"
    return row


def _running_average(previous: float | None, count_before: int, observed: float | None) -> float | None:
    if observed is None:
        return previous
    value = max(0.0, float(observed))
    if previous is None or count_before <= 0:
        return round(value, 2)
    return round((float(previous) * count_before + value) / (count_before + 1), 2)


def _apply_closing_outcome(partner: TitleCompanyPartner, payload: dict[str, Any]) -> dict[str, Any]:
    outcome = str(payload.get("outcome") or "").strip().lower()
    if outcome not in {"closed", "failed", "cancelled"}:
        raise HTTPException(422, "outcome must be closed, failed, or cancelled")
    strategy = str(payload.get("strategy") or "assignment").strip().lower()
    count_before = max(0, int(partner.investor_closings_observed or 0))

    if outcome == "closed":
        partner.investor_closings_observed = count_before + 1
        if strategy in CAPABILITY_FIELDS:
            partner.wholesale_closings_observed = max(0, int(partner.wholesale_closings_observed or 0)) + 1
        partner.avg_title_turnaround_days = _running_average(
            partner.avg_title_turnaround_days,
            count_before,
            payload.get("title_turnaround_days"),
        )
        partner.avg_closing_days = _running_average(
            partner.avg_closing_days,
            count_before,
            payload.get("closing_days"),
        )
        partner.reliability_score = min(100.0, float(partner.reliability_score or 50) + 2.0)
    elif outcome == "failed":
        partner.reliability_score = max(0.0, float(partner.reliability_score or 50) - 10.0)

    if payload.get("fee_quote_accurate") is True:
        partner.fee_transparency_score = min(100.0, float(partner.fee_transparency_score or 50) + 2.0)
    elif payload.get("fee_quote_accurate") is False:
        partner.fee_transparency_score = max(0.0, float(partner.fee_transparency_score or 50) - 5.0)

    capability_field = CAPABILITY_FIELDS.get(strategy)
    if outcome == "closed" and capability_field and payload.get("structure_completed_as_reported") is True:
        setattr(partner, capability_field, "verified")
        partner.last_verified_at = datetime.now(timezone.utc)

    evidence = list(partner.evidence or [])
    evidence.append({
        "source": "sahjony_closing_outcome",
        "deal_id": payload.get("deal_id"),
        "outcome": outcome,
        "strategy": strategy,
        "title_turnaround_days": payload.get("title_turnaround_days"),
        "closing_days": payload.get("closing_days"),
        "fee_quote_accurate": payload.get("fee_quote_accurate"),
        "structure_completed_as_reported": payload.get("structure_completed_as_reported"),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    })
    partner.evidence = evidence[-500:]
    return {"outcome": outcome, "strategy": strategy}


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    partners = db.scalars(select(TitleCompanyPartner).where(
        TitleCompanyPartner.organization_id == principal.organization_id
    ).order_by(TitleCompanyPartner.reliability_score.desc())).all()
    matches = db.scalars(select(TitleCompanyDealMatch).where(
        TitleCompanyDealMatch.organization_id == principal.organization_id
    ).order_by(TitleCompanyDealMatch.score.desc())).all()
    return {
        "organization_id": principal.organization_id,
        "partners": [_serialize_partner(row) for row in partners],
        "matching": {
            "stored_matches": len(matches),
            "eligible_matches": sum(1 for row in matches if row.eligible),
            "recommended_matches": sum(1 for row in matches if row.status == "recommended"),
            "score_semantics": "Title Company Match Confidence = jurisdiction + verified closing strategy + observed wholesale/investor experience + turnaround + reliability + fee transparency + digital closing",
        },
        "learning_loop": "Verified SAHJONY closing outcomes update experience, turnaround, reliability, fee transparency, and observed strategy capability.",
        "evidence_policy": {
            "assignment_friendly": "recommended only when assignment support is verified with evidence",
            "double_close_friendly": "recommended only when double-close support is verified with evidence",
            "legal_status": "title-company capability does not determine whether a transaction structure is lawful in a jurisdiction",
            "selection": "human controlled; ranking never opens title or executes a contract automatically",
        },
    }


@router.post("/partners")
def upsert_partner(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Title company name is required")
    normalized = _normalize_name(name)
    row = db.scalar(select(TitleCompanyPartner).where(
        TitleCompanyPartner.organization_id == principal.organization_id,
        TitleCompanyPartner.normalized_name == normalized,
    ))
    _validate_verified_capabilities(payload, row)
    created = row is None
    if row is None:
        row = TitleCompanyPartner(organization_id=principal.organization_id, name=name, normalized_name=normalized)
        db.add(row)
        db.flush()
        _workspace_link(db, principal.organization_id, "title_company_partner", row.id)
    row.name = name
    row.normalized_name = normalized

    scalar_fields = [
        "website", "phone", "email", "active", "investor_closings_observed", "wholesale_closings_observed",
        "avg_title_turnaround_days", "avg_closing_days", "reliability_score", "fee_transparency_score",
        "underwriter", "license_reference", "notes",
    ]
    for key in scalar_fields:
        if key in payload:
            setattr(row, key, payload.get(key))
    for key in ["states", "counties", "zip_codes", "evidence"]:
        if key in payload:
            setattr(row, key, payload.get(key) or [])
    for key in [
        "assignment_support", "double_close_support", "simultaneous_close_support",
        "transactional_funding_coordination", "remote_closing", "e_signing",
    ]:
        if key in payload:
            setattr(row, key, _capability_status(payload.get(key)))
    if payload.get("verified_now"):
        if not row.evidence:
            raise HTTPException(422, "verified_now requires evidence")
        row.last_verified_at = datetime.now(timezone.utc)

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="title_company_partner_upserted",
        summary=f"{'Added' if created else 'Updated'} title company partner '{row.name}'",
        metadata_json={"title_company_id": row.id, "states": row.states or [], "assignment_support": row.assignment_support, "double_close_support": row.double_close_support},
    ))
    db.commit()
    return {"created": created, "partner": _serialize_partner(row)}


@router.post("/partners/{title_company_id}/closing-outcomes")
def record_closing_outcome(
    title_company_id: int,
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    partner = db.scalar(select(TitleCompanyPartner).where(
        TitleCompanyPartner.id == title_company_id,
        TitleCompanyPartner.organization_id == principal.organization_id,
    ))
    if partner is None:
        raise HTTPException(404, "Title company partner not found")
    deal_id = int(payload.get("deal_id") or 0)
    if deal_id <= 0:
        raise HTTPException(422, "deal_id is required")
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")

    normalized = _apply_closing_outcome(partner, {**payload, "deal_id": deal_id})
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deal_id=deal_id,
        activity_type="title_company_closing_outcome_recorded",
        summary=f"Recorded {normalized['outcome']} outcome for '{partner.name}' on deal #{deal_id}",
        metadata_json={
            "title_company_id": partner.id,
            "outcome": normalized["outcome"],
            "strategy": normalized["strategy"],
            "reliability_score": partner.reliability_score,
            "fee_transparency_score": partner.fee_transparency_score,
            "wholesale_closings_observed": partner.wholesale_closings_observed,
        },
    ))
    db.commit()
    return {"partner": _serialize_partner(partner), "learning_applied": True}


@router.post("/deals/{deal_id}/rank")
def rank_title_companies(
    deal_id: int,
    payload: dict[str, Any] | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    payload = payload or {}
    deal, prop = _deal_context(db, principal, deal_id)
    if str(deal.stage or "").lower() in TERMINAL_DEAL_STAGES:
        raise HTTPException(422, "Cannot rank closing partners for a terminal deal")
    strategy = str(payload.get("strategy") or deal.strategy or "assignment").strip().lower()
    county = str(payload.get("county") or "").strip() or None
    limit = max(1, min(int(payload.get("limit") or 20), 100))
    partners = db.scalars(select(TitleCompanyPartner).where(
        TitleCompanyPartner.organization_id == principal.organization_id,
        TitleCompanyPartner.active.is_(True),
    )).all()

    ranked: list[dict[str, Any]] = []
    for partner in partners:
        intelligence = score_title_company(partner, prop, strategy, county=county)
        match = _upsert_match(db, principal, deal.id, partner, strategy, intelligence)
        ranked.append({
            "title_company_id": partner.id,
            "name": partner.name,
            "score": intelligence["score"],
            "eligible": intelligence["eligible"],
            "evidence_status": intelligence["evidence_status"],
            "status": match.status,
            "components": intelligence["components"],
            "reasons": intelligence["reasons"],
            "contact": {"phone": partner.phone, "email": partner.email, "website": partner.website},
        })
    ranked.sort(key=lambda item: (not item["eligible"], -float(item["score"]), item["name"].lower()))
    ranked = ranked[:limit]
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deal_id=deal.id,
        activity_type="title_company_matches_ranked",
        summary=f"Ranked {len(ranked)} title/closing partners for deal #{deal.id}",
        metadata_json={"strategy": strategy, "state": prop.state, "zip_code": prop.zip_code, "county": county, "top_matches": ranked[:10]},
    ))
    db.commit()
    return {
        "deal_id": deal.id,
        "strategy": strategy,
        "property": {"city": prop.city, "state": prop.state, "zip_code": prop.zip_code, "county": county},
        "matches": ranked,
        "selection_boundary": "Ranking is advisory. Human selection is required before a title order is updated.",
    }


@router.post("/deals/{deal_id}/select/{title_company_id}")
def select_title_company(
    deal_id: int,
    title_company_id: int,
    payload: dict[str, Any] | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    payload = payload or {}
    deal, prop = _deal_context(db, principal, deal_id)
    partner = db.scalar(select(TitleCompanyPartner).where(
        TitleCompanyPartner.id == title_company_id,
        TitleCompanyPartner.organization_id == principal.organization_id,
        TitleCompanyPartner.active.is_(True),
    ))
    if partner is None:
        raise HTTPException(404, "Title company partner not found")
    strategy = str(payload.get("strategy") or deal.strategy or "assignment").strip().lower()
    county = str(payload.get("county") or "").strip() or None
    intelligence = score_title_company(partner, prop, strategy, county=county)
    if not intelligence["eligible"]:
        raise HTTPException(422, {"message": "Selected title company is not evidence-qualified for this deal structure", "reasons": intelligence["reasons"]})

    title = db.scalar(select(TitleOrder).where(
        TitleOrder.organization_id == principal.organization_id,
        TitleOrder.deal_id == deal.id,
    ))
    if title is None:
        title = TitleOrder(organization_id=principal.organization_id, deal_id=deal.id, status="not_ordered")
        db.add(title)
        db.flush()
        _workspace_link(db, principal.organization_id, "title_order", title.id)
    title.title_company = partner.name
    title.contact_name = payload.get("contact_name")
    title.contact_email = payload.get("contact_email") or partner.email
    title.contact_phone = payload.get("contact_phone") or partner.phone
    title.metadata_json = {
        **(title.metadata_json or {}),
        "title_company_partner_id": partner.id,
        "title_company_match_score": intelligence["score"],
        "closing_strategy": strategy,
        "capability_evidence_status": intelligence["evidence_status"],
        "human_selected_by_user_id": principal.user_id,
        "selected_at": datetime.now(timezone.utc).isoformat(),
    }
    match = _upsert_match(db, principal, deal.id, partner, strategy, intelligence)
    match.status = "selected"
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deal_id=deal.id,
        activity_type="title_company_selected",
        summary=f"Selected '{partner.name}' as closing partner for deal #{deal.id}",
        metadata_json={"title_company_id": partner.id, "score": intelligence["score"], "strategy": strategy, "human_selected": True},
    ))
    db.commit()
    return {
        "deal_id": deal.id,
        "title_company_id": partner.id,
        "title_company": partner.name,
        "score": intelligence["score"],
        "status": "selected",
        "title_order_id": title.id,
        "title_order_status": title.status,
    }

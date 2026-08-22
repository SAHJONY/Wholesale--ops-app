from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .buyer_intelligence import rank_buyers
from .database import get_db
from .intelligence_models import IntelligenceConflict, IntelligenceFact
from .models import Buyer, Deal, Lead, Property
from .real_deals import _looks_like_entity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wholesale-os", tags=["wholesale operating system"])

SKILLS: list[dict[str, Any]] = [
    {
        "id": "nationwide-source-discovery",
        "name": "Nationwide Source Discovery",
        "purpose": "Find court, tax, code, deed and government property datasets by jurisdiction.",
        "inputs": ["state", "county", "distress category"],
        "outputs": ["candidate government datasets", "source URL", "validation status"],
        "authoritative_when": "dataset endpoint and schema are validated",
        "risk": "reference_only",
    },
    {
        "id": "owner-deed-verification",
        "name": "Owner & Deed Verification",
        "purpose": "Resolve current owner of record, APN and latest deed from source-bounded intelligence.",
        "inputs": ["property", "assessor/recorder facts"],
        "outputs": ["owner", "owner type", "APN", "last deed", "confidence", "conflicts"],
        "authoritative_when": "county recorder/assessor or equivalent public record is verified",
        "risk": "verification_required",
    },
    {
        "id": "distress-stacking",
        "name": "Distress Signal Stacking",
        "purpose": "Combine tax, code, probate, foreclosure, vacancy and listing signals without promoting assumptions to facts.",
        "inputs": ["public-record facts", "listing facts"],
        "outputs": ["distress stack", "source count", "confidence", "missing evidence"],
        "authoritative_when": "each material signal has provenance",
        "risk": "reference_only",
    },
    {
        "id": "comparable-sales-underwriting",
        "name": "Comparable Sales Underwriting",
        "purpose": "Estimate ARV from supplied licensed/public comps and reject invented comparable sales.",
        "inputs": ["subject property", "recent comparable sales"],
        "outputs": ["ARV", "confidence interval", "warnings", "decision quality"],
        "authoritative_when": "comps carry source, sale date, price, distance and property attributes",
        "risk": "financial_decision_support",
    },
    {
        "id": "rehab-risk",
        "name": "Rehab & Condition Risk",
        "purpose": "Track repair scope and flag unknown roof, HVAC, electrical, plumbing, structure and permitting risk.",
        "inputs": ["inspection", "photos", "permit/condition facts", "repair estimate"],
        "outputs": ["repair budget", "risk flags", "inspection gaps"],
        "authoritative_when": "repair scope is inspection/contractor-backed",
        "risk": "financial_decision_support",
    },
    {
        "id": "mao-assignment",
        "name": "MAO & Assignment Economics",
        "purpose": "Calculate screening buyer price, seller contract ceiling and assignment spread while labeling heuristics explicitly.",
        "inputs": ["ARV", "repairs", "buyer constraints", "target fee", "seller price"],
        "outputs": ["buyer MAO", "target contract", "spread", "margin of safety"],
        "authoritative_when": "ARV, repairs and buyer constraints are verified",
        "risk": "financial_decision_support",
    },
    {
        "id": "buyer-match",
        "name": "Buyer Match",
        "purpose": "Rank real workspace buyers by ZIP, asset type, price, rehab tolerance, POF and reliability.",
        "inputs": ["property economics", "buyer database"],
        "outputs": ["ranked buyers", "response probability", "fit reasons"],
        "authoritative_when": "buyer buy box and proof-of-funds status are current",
        "risk": "reference_only",
    },
    {
        "id": "title-closing-gate",
        "name": "Title & Closing Gate",
        "purpose": "Block contract-ready status until owner authority, deed, liens/title and closing requirements are verified.",
        "inputs": ["owner facts", "deed", "title/liens", "closing checklist"],
        "outputs": ["title readiness", "blocking items", "human approvals"],
        "authoritative_when": "title company/attorney or official record supports the conclusion",
        "risk": "legal_gate",
    },
    {
        "id": "deal-ranking",
        "name": "Nationwide Deal Ranking",
        "purpose": "Rank opportunities by evidence quality, economics, distress, buyer demand and execution risk.",
        "inputs": ["all verified deal facts"],
        "outputs": ["readiness score", "priority", "next best action"],
        "authoritative_when": "underlying material facts are verified",
        "risk": "decision_support",
    },
]

ACCEPTED = {"verified", "partially_verified"}
OWNER_FIELDS = {
    "owner_name", "owner_mailing_address", "apn", "last_sale_price", "last_sale_date",
    "deed_type", "deed_instrument", "tax_delinquency", "code_violation", "probate",
    "lis_pendens", "foreclosure_sale", "notice_of_default", "vacancy",
}


def _ids(db: Session, org_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == org_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _facts(db: Session, org_id: int, property_id: int) -> list[IntelligenceFact]:
    return list(db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == org_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id == property_id,
        IntelligenceFact.field_name.in_(OWNER_FIELDS),
    ).order_by(IntelligenceFact.confidence.desc(), IntelligenceFact.updated_at.desc())).all())


def _fact_value(fact: IntelligenceFact | None):
    if not fact or not isinstance(fact.value_json, dict):
        return None
    return fact.value_json.get("value")


def _best(facts: list[IntelligenceFact], field: str) -> IntelligenceFact | None:
    eligible = [
        fact for fact in facts
        if fact.field_name == field
        and fact.verification_status in ACCEPTED
        and _fact_value(fact) not in (None, "")
    ]
    return eligible[0] if eligible else None


def _value(facts: list[IntelligenceFact], field: str):
    return _fact_value(_best(facts, field))


def _open_conflicts(db: Session, org_id: int, property_id: int) -> list[str]:
    rows = db.scalars(select(IntelligenceConflict).where(
        IntelligenceConflict.organization_id == org_id,
        IntelligenceConflict.entity_type == "property",
        IntelligenceConflict.entity_id == property_id,
        IntelligenceConflict.status == "open",
    )).all()
    return sorted({row.field_name for row in rows})


def _buyer_rows(db: Session, principal: Principal) -> list[Buyer]:
    ids = _ids(db, principal.organization_id, "buyer")
    return list(db.scalars(select(Buyer).where(Buyer.id.in_(ids))).all()) if ids else []


def _buyer_payload(buyer: Buyer) -> dict[str, Any]:
    return {
        "id": buyer.id,
        "name": buyer.name,
        "zip_codes": buyer.zip_codes if isinstance(buyer.zip_codes, list) else [],
        "asset_types": buyer.asset_types if isinstance(buyer.asset_types, list) else [],
        "min_price": buyer.min_price,
        "max_price": buyer.max_price,
        "max_rehab": buyer.max_rehab,
        "closing_days": buyer.closing_days,
        "proof_of_funds_verified": buyer.proof_of_funds_verified,
        "response_rate": buyer.response_rate,
        "reliability_score": buyer.reliability_score,
    }


def _rank_buyer_matches(property_payload: dict[str, Any], buyers: list[Buyer]) -> tuple[list[dict[str, Any]], int]:
    """Rank buyers without allowing one malformed buy box to crash the factory.

    Invalid numeric/list fields are not guessed or silently coerced into a deal fact.
    The offending buyer is omitted from this property's ranking and counted so the
    analysis can surface the evidence gap.
    """
    ranked: list[dict[str, Any]] = []
    invalid = 0
    for buyer in buyers:
        try:
            rows = rank_buyers(property_payload, [_buyer_payload(buyer)])
        except (TypeError, ValueError, OverflowError):
            invalid += 1
            logger.warning(
                "Deal Factory skipped malformed buyer buy box",
                extra={"buyer_id": getattr(buyer, "id", None), "property_id": property_payload.get("id")},
            )
            continue
        ranked.extend(rows)

    ranked.sort(key=lambda row: float(row.get("response_probability") or 0), reverse=True)
    matches = [
        {
            "buyer_id": row.get("buyer_id"),
            "name": row.get("buyer_name"),
            "response_probability": row.get("response_probability"),
            "fit_score": row.get("buy_box_fit"),
            "reasons": row.get("reasons") or [],
        }
        for row in ranked[:5]
    ]
    return matches, invalid


def _source_summary(facts: list[IntelligenceFact]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None]] = set()
    rows = []
    for fact in facts:
        if fact.verification_status not in ACCEPTED:
            continue
        key = (fact.source, fact.source_reference)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "provider": fact.source,
            "reference": fact.source_reference,
            "confidence": fact.confidence,
            "verification_status": fact.verification_status,
            "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
        })
    return rows


def _normalize_distress_signals(value: Any) -> tuple[list[str], list[dict[str, Any]], int]:
    """Return stable labels while preserving structured source evidence.

    Production imports legitimately store distress evidence as objects.  The
    ranking layer historically assumed every item was a hashable string, which
    caused one evidence object to crash the entire property analysis.  Unknown
    shapes are counted, not guessed into a material fact.
    """
    if value in (None, []):
        return [], [], 0
    if not isinstance(value, list):
        return [], [], 1

    labels: list[str] = []
    evidence: list[dict[str, Any]] = []
    invalid = 0
    for item in value:
        if isinstance(item, str):
            label = item.strip()
            if label and label not in labels:
                labels.append(label)
            continue
        if isinstance(item, dict):
            record = dict(item)
            evidence.append(record)
            label = str(record.get("type") or record.get("signal") or "").strip()
            if label and label not in labels:
                labels.append(label)
            elif not label:
                invalid += 1
            continue
        invalid += 1
    return labels, evidence, invalid


def _analysis(db: Session, principal: Principal, prop: Property, buyers: list[Buyer]) -> dict[str, Any]:
    facts = _facts(db, principal.organization_id, prop.id)
    conflicts = _open_conflicts(db, principal.organization_id, prop.id)
    owner_fact = _best(facts, "owner_name")
    owner = str(_fact_value(owner_fact) or "").strip() if owner_fact else ""
    individual_owner = bool(owner and not _looks_like_entity(owner))

    missing: list[str] = []
    if not owner_fact: missing.append("verified owner of record")
    elif not individual_owner: missing.append("individual owner requirement")
    if not _value(facts, "apn"): missing.append("parcel/APN")
    if not _value(facts, "last_sale_date"): missing.append("latest deed/transfer date")
    if prop.arv is None: missing.append("source-backed ARV")
    if prop.repairs is None: missing.append("repair estimate")
    if prop.asking_price is None: missing.append("seller/asking price")
    if conflicts: missing.append("resolve intelligence conflicts")

    screening_buyer_price = None
    spread = None
    if prop.arv is not None and prop.repairs is not None:
        screening_buyer_price = max(0.0, float(prop.arv) * 0.70 - float(prop.repairs))
        if prop.asking_price is not None:
            spread = screening_buyer_price - float(prop.asking_price)

    distress_signals, distress_evidence, invalid_distress = _normalize_distress_signals(prop.distress_signals)
    if invalid_distress:
        missing.append(f"normalize {invalid_distress} malformed distress signal record(s)")

    property_payload = {
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
        "distress_signals": distress_signals,
    }
    buyer_matches, invalid_buyers = _rank_buyer_matches(property_payload, buyers) if buyers else ([], 0)
    if invalid_buyers:
        missing.append(f"{invalid_buyers} buyer buy box record(s) require normalization")

    verified_material = 0
    material_total = 7
    verified_material += int(bool(owner_fact and individual_owner))
    verified_material += int(bool(_value(facts, "apn")))
    verified_material += int(bool(_value(facts, "last_sale_date")))
    verified_material += int(prop.asking_price is not None)
    verified_material += int(prop.arv is not None)
    verified_material += int(prop.repairs is not None)
    verified_material += int(bool(buyer_matches))
    evidence_score = round(100 * verified_material / material_total)

    economics_pass = spread is not None and spread >= 10_000
    ready_for_promotion = (
        not conflicts
        and individual_owner
        and economics_pass
        and prop.property_type == "single_family"
        and not any(x in missing for x in ["parcel/APN", "source-backed ARV", "repair estimate", "seller/asking price"])
    )

    distress = list(dict.fromkeys(distress_signals + [
        field for field in ("tax_delinquency", "code_violation", "probate", "lis_pendens", "foreclosure_sale", "notice_of_default", "vacancy")
        if _value(facts, field) not in (None, False, "", 0)
    ]))

    risk = 100 - evidence_score
    if conflicts: risk = min(100, risk + 20)
    if prop.repairs is None: risk = min(100, risk + 10)
    if not buyer_matches: risk = min(100, risk + 10)

    if ready_for_promotion:
        next_action = "Verify comps/repair scope and title, then promote to Real Deal for human-controlled offer preparation."
    elif not owner_fact:
        next_action = "Verify current individual owner from assessor/recorder evidence."
    elif conflicts:
        next_action = "Resolve conflicting canonical property facts before underwriting."
    elif prop.arv is None or prop.repairs is None:
        next_action = "Complete comp-backed ARV and repair scope."
    elif prop.asking_price is None:
        next_action = "Obtain seller price or listing ask; do not label this a $10K deal without it."
    elif spread is not None and spread < 10_000:
        next_action = "Renegotiate acquisition price or reject; current screening spread is below the $10K target."
    else:
        next_action = "Complete buyer and title verification."

    sources = _source_summary(facts)
    return {
        "property": property_payload,
        "owner": {
            "name": owner or None,
            "type": "individual" if individual_owner else ("entity" if owner else "unknown"),
            "mailing_address": _value(facts, "owner_mailing_address"),
            "verification_status": owner_fact.verification_status if owner_fact else "unverified",
            "confidence": owner_fact.confidence if owner_fact else 0,
        },
        "deed": {
            "apn": _value(facts, "apn"),
            "last_sale_date": _value(facts, "last_sale_date"),
            "last_sale_price": _value(facts, "last_sale_price"),
            "deed_type": _value(facts, "deed_type"),
            "instrument": _value(facts, "deed_instrument"),
        },
        "distress": {
            "signals": distress,
            "count": len(distress),
            "source_records": distress_evidence,
            "invalid_record_count": invalid_distress,
        },
        "economics": {
            "screening_factor": 0.70,
            "screening_buyer_price": screening_buyer_price,
            "seller_price": prop.asking_price,
            "projected_screening_spread": spread,
            "meets_10k_target": economics_pass,
            "authority": "screening_only_not_an_offer",
        },
        "buyers": buyer_matches,
        "evidence": {
            "score": evidence_score,
            "sources": sources,
            "source_count": len(sources),
            "open_conflicts": conflicts,
            "missing": missing,
        },
        "decision": {
            "ready_for_promotion": ready_for_promotion,
            "risk_score": risk,
            "next_action": next_action,
            "human_offer_approval_required": True,
            "legal_financial_actions_autonomous": False,
        },
    }


@router.get("/skills")
def skills(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc),
        "skills": [{**skill, "active": True, "execution_mode": "supervised_read_only"} for skill in SKILLS],
        "policy": {
            "material_fact_traceability_target": 0.95,
            "invented_comps_allowed": False,
            "invented_owner_facts_allowed": False,
            "autonomous_legal_financial_commitments": False,
            "human_approval_required_for_offers_contracts_payments": True,
        },
    }


def _skill_output(skill_id: str, analysis: dict[str, Any]) -> dict[str, Any]:
    prop = analysis["property"]
    outputs: dict[str, Any] = {
        "nationwide-source-discovery": {"jurisdiction": {"city": prop.get("city"), "state": prop.get("state"), "zip_code": prop.get("zip_code")}, "official_records_workspace": "/owner/live-data", "status": "official_source_discovery_available", "requires_human_source_validation": True},
        "owner-deed-verification": {"owner": analysis["owner"], "deed": analysis["deed"], "conflicts": analysis["evidence"]["open_conflicts"], "sources": analysis["evidence"]["sources"]},
        "distress-stacking": analysis["distress"],
        "comparable-sales-underwriting": {"arv": prop.get("arv"), "source_count": analysis["evidence"]["source_count"], "warnings": [gap for gap in analysis["evidence"]["missing"] if "ARV" in gap or "comp" in gap.lower()], "invented_comps_allowed": False},
        "rehab-risk": {"repair_estimate": prop.get("repairs"), "inspection_required": True, "unknown_systems": ["roof", "HVAC", "electrical", "plumbing", "structure", "permits"] if prop.get("repairs") is None else []},
        "mao-assignment": analysis["economics"],
        "buyer-match": {"matches": analysis["buyers"], "match_count": len(analysis["buyers"]), "proof_of_funds_review_required": True},
        "title-closing-gate": {"cleared": not any(gap in analysis["evidence"]["missing"] for gap in ["verified owner of record", "parcel/APN", "latest deed/transfer date"]) and not analysis["evidence"]["open_conflicts"], "blocking_items": analysis["evidence"]["missing"], "human_approval_required": True},
        "deal-ranking": {"evidence_score": analysis["evidence"]["score"], "risk_score": analysis["decision"]["risk_score"], "ready_for_promotion": analysis["decision"]["ready_for_promotion"], "next_best_action": analysis["decision"]["next_action"]},
    }
    return outputs[skill_id]


@router.post("/skills/{skill_id}/run")
def run_skill(skill_id: str, property_id: int, principal: Principal = Depends(require_role("acquisitions")), db: Session = Depends(get_db)):
    skill = next((item for item in SKILLS if item["id"] == skill_id), None)
    if not skill:
        raise HTTPException(404, "Wholesale skill not found")
    lead_ids = set(_ids(db, principal.organization_id, "lead"))
    prop = db.get(Property, property_id)
    if not prop or prop.lead_id not in lead_ids:
        raise HTTPException(404, "Property not found in this workspace")
    analysis = _analysis(db, principal, prop, _buyer_rows(db, principal))
    return {
        "skill": {**skill, "active": True}, "property_id": property_id,
        "executed_at": datetime.now(timezone.utc), "execution_mode": "supervised_read_only",
        "output": _skill_output(skill_id, analysis),
        "safety": {"database_mutated": False, "outreach_sent": False, "offer_created": False, "contract_created": False, "title_status_changed": False, "human_approval_preserved": True},
    }


@router.get("/deal-factory")
def deal_factory(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_ids = _ids(db, principal.organization_id, "lead")
    leads = list(db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()) if lead_ids else []
    buyers = _buyer_rows(db, principal)
    deal_ids = _ids(db, principal.organization_id, "deal")
    deals = list(db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all()) if deal_ids else []
    deals_by_property = {deal.property_id: deal for deal in deals}

    analyses: list[dict[str, Any]] = []
    analysis_warnings: list[dict[str, Any]] = []
    seen_properties: set[int] = set()
    for lead in leads:
        prop = lead.property
        if not prop or prop.id in seen_properties:
            continue
        seen_properties.add(prop.id)
        try:
            analysis = _analysis(db, principal, prop, buyers)
            linked_deal = deals_by_property.get(prop.id)
            analysis["promoted_deal"] = ({
                "id": linked_deal.id,
                "stage": linked_deal.stage,
                "strategy": linked_deal.strategy,
                "target_contract_price": linked_deal.target_contract_price,
                "target_buyer_price": linked_deal.target_buyer_price,
                "projected_assignment_fee": linked_deal.projected_assignment_fee,
                "probability_to_close": linked_deal.probability_to_close,
                "risk_score": linked_deal.risk_score,
                "next_action": linked_deal.next_action,
            } if linked_deal else None)
            analyses.append(analysis)
        except Exception:
            logger.exception(
                "Deal Factory property analysis failed",
                extra={"organization_id": principal.organization_id, "lead_id": lead.id, "property_id": prop.id},
            )
            analysis_warnings.append({
                "lead_id": lead.id,
                "property_id": prop.id,
                "code": "property_analysis_failed",
                "message": "This property was skipped because stored source data requires normalization.",
            })

    analyses.sort(key=lambda row: (
        bool(row["decision"]["ready_for_promotion"]),
        float(row["economics"]["projected_screening_spread"] or -1e12),
        float(row["evidence"]["score"] or 0),
    ), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc),
        "organization_id": principal.organization_id,
        "mode": "source_grounded_nationwide_wholesale_os",
        "summary": {
            "prospects": len(analyses),
            "promotion_ready": sum(bool(row["decision"]["ready_for_promotion"]) for row in analyses),
            "individual_owned": sum(row["owner"]["type"] == "individual" for row in analyses),
            "meets_10k_screen": sum(bool(row["economics"]["meets_10k_target"]) for row in analyses),
            "buyers": len(buyers),
            "promoted_deals": len(deals),
            "analysis_errors": len(analysis_warnings),
        },
        "opportunities": analyses,
        "analysis_warnings": analysis_warnings,
        "skills": [{"id": item["id"], "name": item["name"], "risk": item["risk"]} for item in SKILLS],
        "operating_flow": [
            "Discover public/court/property sources",
            "Verify address and jurisdiction",
            "Verify individual owner + deed/APN",
            "Stack source-backed distress signals",
            "Build source-backed comps and ARV",
            "Estimate repairs and condition risk",
            "Calculate buyer MAO and assignment spread",
            "Match verified buyers",
            "Verify title/closing blockers",
            "Human-controlled offer/contract/disposition/closing",
        ],
    }


@router.get("/properties/{property_id}/analysis")
def property_analysis(property_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_ids = set(_ids(db, principal.organization_id, "lead"))
    prop = db.get(Property, property_id)
    if not prop or prop.lead_id not in lead_ids:
        raise HTTPException(404, "Property not found in this workspace")
    return _analysis(db, principal, prop, _buyer_rows(db, principal))

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .buyer_match_adapter import buyer_to_cash_profile, deal_to_matching_profile, normalize_buyer_type
from .buying_box_intelligence import buyer_match_confidence, buying_box_snapshot, observed_pattern_from_candidate
from .cash_buyer_models import CashBuyerCandidate
from .crm import _assert_linked
from .database import get_db
from .disposition_models import DealBuyerMatch
from .models import Buyer, Deal, Property

router = APIRouter(prefix="/buyer-matching", tags=["buyer matching"])


def _workspace_buyer_ids(db: Session, organization_id: int) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "buyer",
    )).all())


def _workspace_deal(db: Session, principal: Principal, deal_id: int) -> tuple[Deal, Property]:
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    if not prop:
        raise HTTPException(422, "Deal property is missing")
    return deal, prop


def _candidate_by_buyer(db: Session, organization_id: int) -> dict[int, CashBuyerCandidate]:
    rows = db.scalars(select(CashBuyerCandidate).where(
        CashBuyerCandidate.organization_id == organization_id,
        CashBuyerCandidate.promoted_buyer_id.is_not(None),
    )).all()
    return {int(row.promoted_buyer_id): row for row in rows if row.promoted_buyer_id is not None}


@router.get("/buyer-types")
def buyer_types(principal: Principal = Depends(require_role("disposition"))):
    return {
        "organization_id": principal.organization_id,
        "buyer_types": ["individual", "hedge_fund", "entity", "private_capital", "private_investor"],
        "evidence_policy": {
            "proof_of_funds": "must be explicitly verified before assignee selection",
            "closing_history": "must come from recorded/verified closing evidence; never inferred from reliability score",
            "contact_release": "human_approved_only",
        },
    }


@router.get("/snapshot")
def buyer_intelligence_snapshot(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    buyer_ids = _workspace_buyer_ids(db, principal.organization_id)
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    candidates = db.scalars(select(CashBuyerCandidate).where(
        CashBuyerCandidate.organization_id == principal.organization_id
    )).all()
    matches = db.scalars(select(DealBuyerMatch).where(
        DealBuyerMatch.organization_id == principal.organization_id
    )).all()

    buyer_type_counts = Counter(normalize_buyer_type(buyer) for buyer in buyers)
    zip_coverage = sorted({str(zip_code) for buyer in buyers for zip_code in (buyer.zip_codes or []) if str(zip_code).strip()})
    asset_types = Counter(str(asset) for buyer in buyers for asset in (buyer.asset_types or []) if str(asset).strip())
    candidate_status = Counter(str(candidate.status or "unknown") for candidate in candidates)
    matched = [row for row in matches if row.status == "matched"]

    return {
        "organization_id": principal.organization_id,
        "buyer_pool": {
            "total": len(buyers),
            "by_type": dict(buyer_type_counts),
            "proof_of_funds_verified": sum(1 for buyer in buyers if buyer.proof_of_funds_verified),
            "zip_coverage_count": len(zip_coverage),
            "zip_coverage": zip_coverage[:250],
            "asset_types": dict(asset_types),
        },
        "discovery_queue": {
            "total_candidates": len(candidates),
            "by_status": dict(candidate_status),
            "cash_evidence_confirmed": sum(1 for candidate in candidates if candidate.cash_evidence == "confirmed"),
            "repeat_buyers": sum(1 for candidate in candidates if int(candidate.purchase_count or 0) >= 2),
            "promoted": sum(1 for candidate in candidates if candidate.promoted_buyer_id is not None),
        },
        "matching": {
            "stored_matches": len(matches),
            "active_matches": len(matched),
            "score_80_plus": sum(1 for row in matched if float(row.score or 0) >= 80),
            "score_semantics": "Buyer Match Confidence = declared fit + observed purchase fit + capital evidence + closing velocity",
        },
        "evidence_policy": {
            "deed": "proves recorded transfer, not cash by itself",
            "cash": "confirmed only when mortgage-index evidence supports no recorded financing or current POF is explicitly verified",
            "buying_box": "buyer-stated or persisted criteria; observed closing history is supporting evidence, not a declared buying box",
            "contact_release": "human_approved_only",
        },
    }


@router.get("/buyers/{buyer_id}/intelligence")
def buyer_intelligence(
    buyer_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    if buyer_id not in _workspace_buyer_ids(db, principal.organization_id):
        raise HTTPException(404, "Buyer not found")
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(404, "Buyer not found")
    candidate = _candidate_by_buyer(db, principal.organization_id).get(buyer_id)
    profile = buyer_to_cash_profile(buyer)
    observed = observed_pattern_from_candidate(candidate)
    return {
        "buyer_id": buyer.id,
        "buyer_name": buyer.name,
        "buyer_type": profile.buyer_type,
        "buying_box": buying_box_snapshot(profile.buying_box, observed),
        "capital_evidence": {
            "proof_of_funds_verified": bool(profile.proof_of_funds_verified),
            "observed_cash_purchase_count": observed.cash_confirmed_count,
        },
        "evidence_policy": {
            "declared": "current tenant-entered or buyer-stated criteria",
            "observed": "recorded purchase behavior; historical and non-binding",
            "cash": "never inferred from a deed alone",
        },
    }


@router.post("/deals/{deal_id}/rank")
def rank_workspace_buyers(
    deal_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    deal, prop = _workspace_deal(db, principal, deal_id)
    buyer_ids = _workspace_buyer_ids(db, principal.organization_id)
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    candidate_map = _candidate_by_buyer(db, principal.organization_id)
    deal_profile = deal_to_matching_profile(deal, prop)
    limit = max(1, min(int((payload or {}).get("limit") or 25), 100))

    matches = []
    for buyer in buyers:
        profile = buyer_to_cash_profile(buyer)
        observed = observed_pattern_from_candidate(candidate_map.get(buyer.id))
        intelligence = buyer_match_confidence(profile, deal_profile, observed)
        if not intelligence["eligible"]:
            continue
        matches.append({
            "buyer_id": buyer.id,
            "display_name": buyer.name,
            "buyer_type": profile.buyer_type,
            "score": intelligence["confidence"],
            "confidence": intelligence["confidence"],
            "components": intelligence["components"],
            "declared_reasons": intelligence["declared_reasons"],
            "observed_reasons": intelligence["observed_reasons"],
            "contact_release": "human_approved_only",
        })
    matches.sort(key=lambda item: (-float(item["confidence"]), str(item["display_name"]).lower()))
    matches = matches[:limit]

    existing = {
        row.buyer_id: row
        for row in db.scalars(select(DealBuyerMatch).where(
            DealBuyerMatch.organization_id == principal.organization_id,
            DealBuyerMatch.deal_id == deal_id,
        )).all()
    }
    matched_ids: set[int] = set()
    for match in matches:
        buyer_id = int(match["buyer_id"])
        matched_ids.add(buyer_id)
        row = existing.get(buyer_id) or DealBuyerMatch(
            organization_id=principal.organization_id,
            deal_id=deal_id,
            buyer_id=buyer_id,
        )
        row.score = float(match["confidence"])
        row.reasons = list(match["declared_reasons"]) + list(match["observed_reasons"])
        row.status = "matched"
        db.add(row)

    for buyer_id, row in existing.items():
        if buyer_id not in matched_ids:
            row.status = "outside_buying_box"
            row.score = 0
            row.reasons = ["outside_current_buying_box"]

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deal_id=deal_id,
        activity_type="buying_box_intelligence_ranked",
        summary=f"Ranked {len(matches)} buyers using declared and observed buying-box intelligence for deal #{deal_id}",
        metadata_json={
            "buyer_pool": len(buyers),
            "eligible_matches": len(matches),
            "top_matches": matches[:20],
            "matching_engine": "buying_box_intelligence_v2",
            "weights": {"declared": 0.50, "observed": 0.25, "capital": 0.15, "velocity": 0.10},
            "contact_release": "human_approved_only",
        },
    ))
    db.commit()

    return {
        "deal_id": deal_id,
        "property_id": prop.id,
        "buyer_pool": len(buyers),
        "eligible_matches": len(matches),
        "matches": matches,
        "score_semantics": "Buyer Match Confidence",
        "weights": {"declared_buying_box_fit": 0.50, "observed_purchase_fit": 0.25, "capital_evidence": 0.15, "closing_velocity": 0.10},
        "contact_release": "human_approved_only",
        "proof_of_funds_required_before_selection": True,
    }

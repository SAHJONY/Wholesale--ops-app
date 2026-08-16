from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .buyer_match_adapter import buyer_to_cash_profile, deal_to_matching_profile
from .cash_buyer_matching import rank_buyers
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

    profiles = [buyer_to_cash_profile(buyer) for buyer in buyers]
    deal_profile = deal_to_matching_profile(deal, prop)
    limit = max(1, min(int((payload or {}).get("limit") or 25), 100))
    matches = rank_buyers(deal_profile, profiles, limit=limit)

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
        row.score = float(match["score"])
        row.reasons = list(match["reasons"])
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
        activity_type="evidence_aware_buyer_matches_refreshed",
        summary=f"Ranked {len(matches)} evidence-aware cash buyers for deal #{deal_id}",
        metadata_json={
            "buyer_pool": len(buyers),
            "eligible_matches": len(matches),
            "top_matches": matches[:20],
            "matching_engine": "buying_box_v1",
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
        "contact_release": "human_approved_only",
        "proof_of_funds_required_before_selection": True,
    }

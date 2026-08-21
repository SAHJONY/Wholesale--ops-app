from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .buyer_match_api import rank_workspace_buyers
from .closing_command_models import FundingRecord
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .disposition_models import AssignmentSelection, BuyerOffer, DealBuyerMatch, DispositionCampaign
from .models import Approval, Buyer, Deal, Property

router = APIRouter(prefix="/disposition", tags=["buyer disposition"])


def _deal(db: Session, principal: Principal, deal_id: int):
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    if not prop:
        raise HTTPException(422, "Deal property is missing")
    # Jurisdiction-specific policy gates belong in compliance/outreach policy,
    # not in disposition discovery or buyer matching. Texas is supported here.
    return deal, prop


def _linked_buyer_ids(db: Session, organization_id: int) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "buyer",
    )).all())


def _rank_offer(offer: BuyerOffer, buyer: Buyer, deal: Deal) -> float:
    target = float(deal.target_buyer_price or deal.target_contract_price or 1)
    price_score = min(55.0, max(0.0, float(offer.amount) / max(target, 1) * 45.0))
    pof = 20.0 if offer.proof_of_funds_status == "verified" else 0.0
    speed = max(0.0, 15.0 - max(0, int(offer.closing_days or 30) - 7) * 0.5)
    reliability = min(10.0, float(buyer.reliability_score or 0) / 10.0)
    contingency_penalty = min(20.0, len(offer.contingencies or []) * 5.0)
    return round(max(0.0, min(100.0, price_score + pof + speed + reliability - contingency_penalty)), 2)


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    deal_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
    )).all())
    buyer_ids = _linked_buyer_ids(db, principal.organization_id)
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids)).order_by(Deal.updated_at.desc())).all() if deal_ids else []
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    campaigns = db.scalars(select(DispositionCampaign).where(DispositionCampaign.organization_id == principal.organization_id).order_by(DispositionCampaign.created_at.desc())).all()
    matches = db.scalars(select(DealBuyerMatch).where(DealBuyerMatch.organization_id == principal.organization_id).order_by(DealBuyerMatch.score.desc())).all()
    offers = db.scalars(select(BuyerOffer).where(BuyerOffer.organization_id == principal.organization_id).order_by(BuyerOffer.ranking_score.desc())).all()
    selections = db.scalars(select(AssignmentSelection).where(AssignmentSelection.organization_id == principal.organization_id)).all()
    buyer_map = {b.id: b for b in buyers}
    return {
        "deals": [{"id": d.id, "stage": d.stage, "property_id": d.property_id, "target_contract_price": d.target_contract_price, "target_buyer_price": d.target_buyer_price, "projected_assignment_fee": d.projected_assignment_fee, "next_action": d.next_action} for d in deals],
        "buyers": [{"id": b.id, "name": b.name, "company": b.company, "buyer_type": b.buyer_type, "email": b.email, "phone": b.phone, "proof_of_funds_verified": b.proof_of_funds_verified, "reliability_score": b.reliability_score, "closing_days": b.closing_days} for b in buyers],
        "campaigns": [{"id": c.id, "deal_id": c.deal_id, "name": c.name, "status": c.status, "asking_price": c.asking_price, "audience_count": c.audience_count, "sent_count": c.sent_count, "response_count": c.response_count, "created_at": c.created_at} for c in campaigns],
        "matches": [{"id": m.id, "deal_id": m.deal_id, "buyer_id": m.buyer_id, "buyer_name": buyer_map[m.buyer_id].name if m.buyer_id in buyer_map else f"Buyer #{m.buyer_id}", "score": m.score, "reasons": m.reasons, "status": m.status} for m in matches],
        "offers": [{"id": o.id, "deal_id": o.deal_id, "buyer_id": o.buyer_id, "buyer_name": buyer_map[o.buyer_id].name if o.buyer_id in buyer_map else f"Buyer #{o.buyer_id}", "amount": o.amount, "earnest_money": o.earnest_money, "closing_days": o.closing_days, "proof_of_funds_status": o.proof_of_funds_status, "contingencies": o.contingencies, "status": o.status, "ranking_score": o.ranking_score, "submitted_at": o.submitted_at} for o in offers],
        "selections": [{"id": s.id, "deal_id": s.deal_id, "buyer_id": s.buyer_id, "buyer_offer_id": s.buyer_offer_id, "assignment_price": s.assignment_price, "assignment_fee": s.assignment_fee, "status": s.status, "approval_id": s.approval_id} for s in selections],
        "buyer_matching_engine": "buying_box_intelligence_v2",
    }


@router.post("/deals/{deal_id}/match-buyers")
def refresh_matches(deal_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    # Backward-compatible disposition route; one scoring source of truth.
    return rank_workspace_buyers(deal_id, None, principal, db)


@router.post("/deals/{deal_id}/campaigns")
def create_campaign(deal_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    deal, _ = _deal(db, principal, deal_id)
    minimum_score = float(payload.get("minimum_match_score") or 50)
    audience_count = len(db.scalars(select(DealBuyerMatch).where(
        DealBuyerMatch.organization_id == principal.organization_id,
        DealBuyerMatch.deal_id == deal_id,
        DealBuyerMatch.status == "matched",
        DealBuyerMatch.score >= minimum_score,
    )).all())
    campaign = DispositionCampaign(
        organization_id=principal.organization_id,
        deal_id=deal_id,
        name=str(payload.get("name") or f"Deal #{deal_id} buyer campaign"),
        status="pending_approval",
        asking_price=float(payload.get("asking_price") or deal.target_buyer_price or 0),
        minimum_assignment_fee=float(payload.get("minimum_assignment_fee") or deal.projected_assignment_fee or 0),
        audience_count=audience_count,
        payload={"minimum_match_score": minimum_score, "channels": payload.get("channels") or ["email", "sms"], "public_address_hidden": True, "matching_engine": "buying_box_intelligence_v2"},
    )
    db.add(campaign); db.flush(); _workspace_link(db, principal.organization_id, "disposition_campaign", campaign.id)
    approval = Approval(action_type="launch_disposition_campaign", status="pending", entity_type="disposition_campaign", entity_id=campaign.id, summary=f"Approve buyer campaign for deal #{deal_id}", payload={"campaign_id": campaign.id, "deal_id": deal_id, "audience_count": audience_count})
    db.add(approval); db.flush(); _workspace_link(db, principal.organization_id, "approval", approval.id)
    db.commit()
    return {"campaign_id": campaign.id, "approval_id": approval.id, "status": campaign.status, "audience_count": audience_count}


@router.post("/deals/{deal_id}/offers")
def record_offer(deal_id: int, payload: dict, principal: Principal = Depends(require_role("disposition")), db: Session = Depends(get_db)):
    deal, _ = _deal(db, principal, deal_id)
    buyer_id = int(payload.get("buyer_id") or 0)
    _assert_linked(db, principal, "buyer", buyer_id)
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(404, "Buyer not found")
    amount = float(payload.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(422, "Offer amount must be positive")
    offer = BuyerOffer(organization_id=principal.organization_id, deal_id=deal_id, buyer_id=buyer_id, campaign_id=payload.get("campaign_id"), amount=amount, earnest_money=float(payload.get("earnest_money") or 0), closing_days=int(payload.get("closing_days") or buyer.closing_days or 14), proof_of_funds_status=str(payload.get("proof_of_funds_status") or ("verified" if buyer.proof_of_funds_verified else "missing")), proof_of_funds_reference=payload.get("proof_of_funds_reference"), contingencies=payload.get("contingencies") or [], notes=payload.get("notes"))
    offer.ranking_score = _rank_offer(offer, buyer, deal)
    db.add(offer); db.flush(); _workspace_link(db, principal.organization_id, "buyer_offer", offer.id)
    db.add(CrmActivity(organization_id=principal.organization_id, user_id=principal.user_id, deal_id=deal_id, activity_type="buyer_offer_received", summary=f"Buyer offer received from {buyer.name}: ${amount:,.0f}", metadata_json={"offer_id": offer.id, "buyer_id": buyer.id, "ranking_score": offer.ranking_score}))
    db.commit()
    return {"offer_id": offer.id, "ranking_score": offer.ranking_score, "status": offer.status}


@router.post("/offers/{offer_id}/select")
def select_offer(offer_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    offer = db.get(BuyerOffer, offer_id)
    if not offer or offer.organization_id != principal.organization_id:
        raise HTTPException(404, "Buyer offer not found")
    deal, _ = _deal(db, principal, offer.deal_id)
    if offer.proof_of_funds_status != "verified":
        raise HTTPException(422, "Verified proof of funds is required before assignee selection")
    assignment_fee = round(float(offer.amount) - float(deal.target_contract_price or 0), 2)
    if assignment_fee <= 0:
        raise HTTPException(422, "Selected offer does not produce a positive assignment fee")
    selection = db.scalar(select(AssignmentSelection).where(AssignmentSelection.organization_id == principal.organization_id, AssignmentSelection.deal_id == deal.id))
    if not selection:
        selection = AssignmentSelection(organization_id=principal.organization_id, deal_id=deal.id, buyer_id=offer.buyer_id, buyer_offer_id=offer.id, assignment_price=offer.amount, assignment_fee=assignment_fee, selected_by_user_id=principal.user_id, status="pending_approval", notes=payload.get("notes"))
        db.add(selection); db.flush(); _workspace_link(db, principal.organization_id, "assignment_selection", selection.id)
    approval = Approval(action_type="approve_assignment_buyer", status="pending", entity_type="assignment_selection", entity_id=selection.id, summary=f"Approve buyer #{offer.buyer_id} for deal #{deal.id} at ${offer.amount:,.0f}", payload={"selection_id": selection.id, "deal_id": deal.id, "offer_id": offer.id, "assignment_price": offer.amount, "assignment_fee": assignment_fee})
    db.add(approval); db.flush(); _workspace_link(db, principal.organization_id, "approval", approval.id)
    selection.approval_id = approval.id
    db.commit()
    return {"selection_id": selection.id, "approval_id": approval.id, "status": selection.status, "assignment_fee": assignment_fee}


@router.post("/selections/{selection_id}/finalize")
def finalize_selection(selection_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    selection = db.get(AssignmentSelection, selection_id)
    if not selection or selection.organization_id != principal.organization_id:
        raise HTTPException(404, "Assignment selection not found")
    approval = db.get(Approval, selection.approval_id) if selection.approval_id else None
    if not approval or approval.status != "approved":
        raise HTTPException(409, "Owner approval is required before finalizing the assignee")
    deal, _ = _deal(db, principal, selection.deal_id)
    buyer = db.get(Buyer, selection.buyer_id)
    offer = db.get(BuyerOffer, selection.buyer_offer_id)
    if not offer:
        raise HTTPException(422, "Selected buyer offer is missing")
    selection.status = "finalized"; offer.status = "selected"; offer.selected_at = datetime.now(timezone.utc)
    deal.target_buyer_price = selection.assignment_price
    deal.projected_assignment_fee = selection.assignment_fee
    deal.stage = "buyer_selected"
    deal.next_action = "Prepare assignment agreement and confirm buyer funding"
    funding = db.scalar(select(FundingRecord).where(FundingRecord.organization_id == principal.organization_id, FundingRecord.deal_id == deal.id))
    if not funding:
        funding = FundingRecord(organization_id=principal.organization_id, deal_id=deal.id)
        db.add(funding)
    funding.buyer_name = buyer.name if buyer else f"Buyer #{selection.buyer_id}"
    funding.required_amount = selection.assignment_price
    funding.proof_of_funds_status = offer.proof_of_funds_status
    funding.proof_of_funds_reference = offer.proof_of_funds_reference
    funding.status = "verified" if offer.proof_of_funds_status == "verified" else "pending"
    db.add(CrmActivity(organization_id=principal.organization_id, user_id=principal.user_id, deal_id=deal.id, activity_type="assignment_buyer_finalized", summary=f"Assignee finalized at ${selection.assignment_price:,.0f}; projected fee ${selection.assignment_fee:,.0f}", metadata_json={"selection_id": selection.id, "buyer_id": selection.buyer_id, "offer_id": offer.id}))
    db.commit()
    return {"selection_id": selection.id, "status": selection.status, "deal_stage": deal.stage, "assignment_price": selection.assignment_price, "assignment_fee": selection.assignment_fee}

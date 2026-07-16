from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from .autonomy import create_task
from .models import AcquisitionRun, Approval, Buyer, ClosingItem, Deal, Lead, Offer, Property
from .services import lead_score, match_buyer

ACQUISITION_SOURCES = [
    "tax_delinquent", "probate", "code_violations", "vacant_property",
    "absentee_owner", "pre_foreclosure", "aged_mls", "fsbo",
    "driving_for_dollars", "commercial_distress",
]

DEFAULT_MARKETS = [
    "Pensacola FL", "Atlanta GA", "Tampa FL", "Jacksonville FL",
    "Cleveland OH", "Birmingham AL", "Springfield MO",
]


def schedule_acquisition_runs(db: Session, markets: list[str] | None = None,
                              sources: list[str] | None = None) -> list[AcquisitionRun]:
    runs = []
    for market in markets or DEFAULT_MARKETS:
        for source in sources or ACQUISITION_SOURCES:
            run = AcquisitionRun(
                source_type=source,
                market=market,
                status="queued",
                configuration={"mode": "licensed_or_public_data_only", "exclude_states": ["TX"]},
            )
            db.add(run)
            runs.append(run)
    db.commit()
    for run in runs:
        db.refresh(run)
        create_task(
            db,
            "acquisition_source_run",
            {"acquisition_run_id": run.id, "source_type": run.source_type, "market": run.market},
            priority=70,
        )
    return runs


def create_or_update_deal(db: Session, property_id: int) -> Deal:
    prop = db.get(Property, property_id)
    if not prop:
        raise ValueError("Property not found")
    deal = db.scalar(select(Deal).where(Deal.property_id == property_id))
    if not deal:
        assignment_fee = 15000.0
        target_contract = prop.mao
        target_buyer = (target_contract + assignment_fee) if target_contract else None
        lead = prop.lead
        score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
        deal = Deal(
            property_id=property_id,
            stage="qualified" if score >= 70 else "nurture",
            strategy="assignment",
            target_contract_price=target_contract,
            target_buyer_price=target_buyer,
            projected_assignment_fee=assignment_fee,
            probability_to_close=min(95, max(5, score)),
            risk_score=max(5, 100 - score),
            next_action="Verify comps and seller authority; prepare approval-gated offer",
            metadata_json={"lead_score": score},
        )
        db.add(deal)
        db.commit()
        db.refresh(deal)
    return deal


def build_seller_offer(db: Session, deal_id: int, amount: float | None = None) -> tuple[Offer, Approval]:
    deal = db.get(Deal, deal_id)
    if not deal:
        raise ValueError("Deal not found")
    offer_amount = amount or deal.target_contract_price
    if not offer_amount:
        raise ValueError("No offer amount available")
    offer = Offer(
        deal_id=deal.id,
        offer_type="seller_offer",
        amount=offer_amount,
        status="pending_approval",
        terms={
            "earnest_money": 100,
            "closing_timeline": "30 days from the third day after signature",
            "assignment_allowed": True,
            "buyer_name": "Juan Gonzalez",
        },
    )
    db.add(offer)
    db.flush()
    approval = Approval(
        action_type="send_seller_offer",
        entity_type="offer",
        entity_id=offer.id,
        summary=f"Approve seller offer of ${offer_amount:,.0f}",
        payload={"deal_id": deal.id, "offer_id": offer.id, "amount": offer_amount},
    )
    db.add(approval)
    db.commit()
    db.refresh(offer)
    db.refresh(approval)
    return offer, approval


def initialize_closing(db: Session, deal_id: int) -> list[ClosingItem]:
    deal = db.get(Deal, deal_id)
    if not deal:
        raise ValueError("Deal not found")
    existing = db.scalars(select(ClosingItem).where(ClosingItem.deal_id == deal_id)).all()
    if existing:
        return existing
    item_types = [
        "executed_purchase_agreement", "earnest_money", "title_search",
        "lien_review", "inspection_access", "buyer_proof_of_funds",
        "assignment_agreement", "closing_statement", "funding_confirmation",
    ]
    items = [ClosingItem(deal_id=deal_id, item_type=item, owner="transaction-coordinator") for item in item_types]
    db.add_all(items)
    deal.stage = "closing"
    deal.next_action = "Complete closing checklist and resolve title exceptions"
    db.commit()
    return items


def executive_brief(db: Session) -> dict:
    leads = db.scalars(select(Lead)).all()
    deals = db.scalars(select(Deal)).all()
    approvals = db.scalars(select(Approval).where(Approval.status == "pending")).all()
    buyers = db.scalars(select(Buyer)).all()
    projected = sum(item.projected_assignment_fee or 0 for item in deals if item.stage not in {"closed", "dead"})
    hot = [lead for lead in leads if lead_score(lead.motivation_score, lead.equity_score, lead.distress_score) >= 70]
    priorities = []
    if approvals:
        priorities.append(f"Review {len(approvals)} pending approval(s)")
    if hot:
        priorities.append(f"Contact {len(hot)} hot seller lead(s)")
    if deals:
        priorities.append(f"Advance {len([d for d in deals if d.stage != 'closed'])} active deal(s)")
    if not priorities:
        priorities.append("Run acquisition sources and import verified leads")
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "new_leads": len(leads),
        "hot_leads": len(hot),
        "active_deals": len([d for d in deals if d.stage not in {"closed", "dead"}]),
        "qualified_buyers": len([b for b in buyers if b.reliability_score >= 70]),
        "pending_approvals": len(approvals),
        "projected_assignment_revenue": projected,
        "priorities": priorities,
    }


def buyer_appetite(db: Session, property_id: int) -> list[dict]:
    prop = db.get(Property, property_id)
    if not prop:
        raise ValueError("Property not found")
    ranked = []
    for buyer in db.scalars(select(Buyer)).all():
        score, reasons = match_buyer(buyer, prop)
        probability = min(98, max(1, score * 0.85 + buyer.response_rate * 0.15))
        ranked.append({
            "buyer_id": buyer.id,
            "buyer_name": buyer.name,
            "match_score": score,
            "predicted_response_probability": round(probability, 1),
            "estimated_close_days": buyer.closing_days,
            "proof_of_funds_verified": buyer.proof_of_funds_verified,
            "reasons": reasons,
        })
    return sorted(ranked, key=lambda item: item["predicted_response_probability"], reverse=True)

from __future__ import annotations

from .cash_buyer_matching import BuyingBox, CashBuyer, DealForMatching
from .models import Buyer, Deal, Property


def normalize_buyer_type(buyer: Buyer) -> str:
    raw = str(buyer.buyer_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "individual": "individual",
        "cash_buyer": "entity" if buyer.company else "individual",
        "investor": "private_investor",
        "private_investor": "private_investor",
        "private_capital": "private_capital",
        "private_equity": "private_capital",
        "hedge_fund": "hedge_fund",
        "fund": "hedge_fund",
        "entity": "entity",
        "llc": "entity",
        "corporation": "entity",
        "company": "entity",
    }
    return aliases.get(raw, "entity" if buyer.company else "individual")


def buyer_to_cash_profile(buyer: Buyer) -> CashBuyer:
    box = BuyingBox(
        zip_codes=tuple(str(value).strip() for value in (buyer.zip_codes or []) if str(value).strip()),
        property_types=tuple(str(value).strip() for value in (buyer.asset_types or []) if str(value).strip()),
        min_price=float(buyer.min_price) if buyer.min_price is not None else None,
        max_price=float(buyer.max_price) if buyer.max_price is not None else None,
        max_rehab=float(buyer.max_rehab) if buyer.max_rehab is not None else None,
    )
    return CashBuyer(
        buyer_id=str(buyer.id),
        display_name=str(buyer.name),
        buyer_type=normalize_buyer_type(buyer),
        buying_box=box,
        verified_cash_buyer=bool(buyer.proof_of_funds_verified),
        proof_of_funds_verified=bool(buyer.proof_of_funds_verified),
        # The legacy Buyer table does not persist deed/closing-history evidence.
        # Never infer that evidence from reliability_score or response_rate.
        closing_history_verified=False,
        active=True,
        source_urls=(),
        notes="Legacy tenant buyer normalized into the evidence-aware buying-box matcher.",
    )


def deal_to_matching_profile(deal: Deal, prop: Property) -> DealForMatching:
    assignment_price = (
        deal.target_buyer_price
        if deal.target_buyer_price is not None
        else deal.target_contract_price
        if deal.target_contract_price is not None
        else prop.mao
        if prop.mao is not None
        else prop.asking_price
    )
    assignment_fee = deal.projected_assignment_fee
    return DealForMatching(
        state=str(prop.state or ""),
        city=str(prop.city or ""),
        zip_code=str(prop.zip_code or ""),
        property_type=str(prop.property_type or ""),
        strategy=str(deal.strategy or "wholesale"),
        assignment_price=float(assignment_price) if assignment_price is not None else None,
        arv=float(prop.arv) if prop.arv is not None else None,
        rehab=float(prop.repairs) if prop.repairs is not None else None,
        beds=int(prop.bedrooms) if prop.bedrooms is not None else None,
        baths=float(prop.bathrooms) if prop.bathrooms is not None else None,
        sqft=int(prop.sqft) if prop.sqft is not None else None,
        distress_signals=tuple(str(value) for value in (prop.distress_signals or [])),
        assignment_fee=float(assignment_fee) if assignment_fee is not None else None,
    )

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BUYER_TYPES = {
    "individual",
    "hedge_fund",
    "entity",
    "private_capital",
    "private_investor",
}


@dataclass(frozen=True)
class BuyingBox:
    states: tuple[str, ...] = ()
    counties: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    zip_codes: tuple[str, ...] = ()
    property_types: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    min_price: float | None = None
    max_price: float | None = None
    min_arv: float | None = None
    max_arv: float | None = None
    min_equity_pct: float | None = None
    max_rehab: float | None = None
    min_beds: int | None = None
    min_baths: float | None = None
    min_sqft: int | None = None
    max_sqft: int | None = None
    min_year_built: int | None = None
    max_year_built: int | None = None
    occupancy: tuple[str, ...] = ()
    distress_signals: tuple[str, ...] = ()
    max_assignment_fee: float | None = None


@dataclass(frozen=True)
class CashBuyer:
    buyer_id: str
    display_name: str
    buyer_type: str
    buying_box: BuyingBox
    verified_cash_buyer: bool = False
    proof_of_funds_verified: bool = False
    closing_history_verified: bool = False
    active: bool = True
    source_urls: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class DealForMatching:
    state: str
    county: str = ""
    city: str = ""
    zip_code: str = ""
    property_type: str = ""
    strategy: str = "wholesale"
    assignment_price: float | None = None
    arv: float | None = None
    equity_pct: float | None = None
    rehab: float | None = None
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    year_built: int | None = None
    occupancy: str = ""
    distress_signals: tuple[str, ...] = ()
    assignment_fee: float | None = None


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _in(values: tuple[str, ...], value: str) -> bool:
    return not values or _norm(value) in {_norm(v) for v in values}


def _range_ok(value: float | int | None, minimum: float | int | None, maximum: float | int | None) -> bool:
    if value is None:
        return minimum is None and maximum is None
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def match_buyer_to_deal(buyer: CashBuyer, deal: DealForMatching) -> dict[str, Any]:
    if buyer.buyer_type not in BUYER_TYPES:
        return {"eligible": False, "score": 0, "reasons": ["unsupported_buyer_type"]}
    if not buyer.active:
        return {"eligible": False, "score": 0, "reasons": ["inactive_buyer"]}

    box = buyer.buying_box
    hard_checks = {
        "state": _in(box.states, deal.state),
        "county": _in(box.counties, deal.county),
        "city": _in(box.cities, deal.city),
        "zip": _in(box.zip_codes, deal.zip_code),
        "property_type": _in(box.property_types, deal.property_type),
        "strategy": _in(box.strategies, deal.strategy),
        "price": _range_ok(deal.assignment_price, box.min_price, box.max_price),
        "arv": _range_ok(deal.arv, box.min_arv, box.max_arv),
        "rehab": _range_ok(deal.rehab, None, box.max_rehab),
        "beds": _range_ok(deal.beds, box.min_beds, None),
        "baths": _range_ok(deal.baths, box.min_baths, None),
        "sqft": _range_ok(deal.sqft, box.min_sqft, box.max_sqft),
        "year_built": _range_ok(deal.year_built, box.min_year_built, box.max_year_built),
        "occupancy": _in(box.occupancy, deal.occupancy),
        "assignment_fee": _range_ok(deal.assignment_fee, None, box.max_assignment_fee),
    }
    if box.min_equity_pct is not None:
        hard_checks["equity"] = deal.equity_pct is not None and deal.equity_pct >= box.min_equity_pct
    if box.distress_signals:
        hard_checks["distress"] = bool({_norm(x) for x in box.distress_signals} & {_norm(x) for x in deal.distress_signals})

    failed = [key for key, ok in hard_checks.items() if not ok]
    if failed:
        return {"eligible": False, "score": 0, "reasons": [f"outside_buying_box:{x}" for x in failed]}

    score = 60
    reasons = ["inside_buying_box"]
    if buyer.verified_cash_buyer:
        score += 10
        reasons.append("cash_buyer_verified")
    if buyer.proof_of_funds_verified:
        score += 15
        reasons.append("proof_of_funds_verified")
    if buyer.closing_history_verified:
        score += 15
        reasons.append("closing_history_verified")

    return {"eligible": True, "score": min(score, 100), "reasons": reasons}


def rank_buyers(deal: DealForMatching, buyers: list[CashBuyer], limit: int = 25) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for buyer in buyers:
        result = match_buyer_to_deal(buyer, deal)
        if not result["eligible"]:
            continue
        matches.append({
            "buyer_id": buyer.buyer_id,
            "display_name": buyer.display_name,
            "buyer_type": buyer.buyer_type,
            "score": result["score"],
            "reasons": result["reasons"],
            "source_urls": list(buyer.source_urls),
            "contact_release": "human_approved_only",
        })
    matches.sort(key=lambda item: (-item["score"], item["display_name"].lower()))
    return matches[: max(1, min(limit, 100))]

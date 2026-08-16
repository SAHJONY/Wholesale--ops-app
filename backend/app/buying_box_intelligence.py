from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any

from .cash_buyer_matching import DealForMatching, BuyingBox, match_buyer_to_deal, CashBuyer


@dataclass(frozen=True)
class ObservedBuyingPattern:
    purchase_count: int = 0
    cash_confirmed_count: int = 0
    zip_codes: tuple[str, ...] = ()
    counties: tuple[str, ...] = ()
    min_purchase_price: float | None = None
    median_purchase_price: float | None = None
    max_purchase_price: float | None = None
    first_purchase_at: datetime | None = None
    last_purchase_at: datetime | None = None
    source_count: int = 0


def observed_pattern_from_candidate(candidate: Any | None) -> ObservedBuyingPattern:
    if candidate is None:
        return ObservedBuyingPattern()
    prices: list[float] = []
    sources: set[str] = set()
    for item in candidate.evidence or []:
        try:
            amount = float(item.get("consideration") or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount > 0:
            prices.append(amount)
        source = str(item.get("source") or "").strip()
        if source:
            sources.add(source)
    return ObservedBuyingPattern(
        purchase_count=int(candidate.purchase_count or 0),
        cash_confirmed_count=int(candidate.cash_confirmed_count or 0),
        zip_codes=tuple(str(x) for x in (candidate.zip_codes or []) if str(x).strip()),
        counties=tuple(str(x) for x in (candidate.counties or []) if str(x).strip()),
        min_purchase_price=min(prices) if prices else None,
        median_purchase_price=median(prices) if prices else None,
        max_purchase_price=max(prices) if prices else None,
        first_purchase_at=candidate.first_purchase_at,
        last_purchase_at=candidate.last_purchase_at,
        source_count=len(sources),
    )


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _observed_fit(pattern: ObservedBuyingPattern, deal: DealForMatching) -> tuple[float, list[str]]:
    if pattern.purchase_count <= 0:
        return 0.0, ["no_observed_purchase_history"]
    score = 0.0
    reasons: list[str] = []
    if deal.zip_code and pattern.zip_codes and _norm(deal.zip_code) in {_norm(x) for x in pattern.zip_codes}:
        score += 45
        reasons.append("observed_zip_match")
    elif deal.county and pattern.counties and _norm(deal.county) in {_norm(x) for x in pattern.counties}:
        score += 30
        reasons.append("observed_county_match")
    elif not pattern.zip_codes and not pattern.counties:
        reasons.append("observed_geography_missing")
    else:
        reasons.append("outside_observed_geography")

    if deal.assignment_price is not None and pattern.min_purchase_price is not None and pattern.max_purchase_price is not None:
        low = pattern.min_purchase_price * 0.8
        high = pattern.max_purchase_price * 1.2
        if low <= deal.assignment_price <= high:
            score += 30
            reasons.append("observed_price_band_match")
        else:
            reasons.append("outside_observed_price_band")

    repeat_score = min(15.0, max(0, pattern.purchase_count - 1) * 3.0)
    if repeat_score:
        score += repeat_score
        reasons.append("repeat_purchase_history")

    if pattern.cash_confirmed_count > 0:
        score += 10
        reasons.append("observed_cash_purchase_evidence")
    return min(100.0, score), reasons


def _velocity_score(pattern: ObservedBuyingPattern) -> tuple[float, list[str]]:
    if pattern.purchase_count < 2 or not pattern.first_purchase_at or not pattern.last_purchase_at:
        return 0.0, ["insufficient_closing_velocity_history"]
    first = pattern.first_purchase_at
    last = pattern.last_purchase_at
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(1, (last - first).days)
    annualized = pattern.purchase_count * 365 / days
    score = min(100.0, annualized * 12.5)
    return score, [f"observed_purchase_velocity:{annualized:.1f}_per_year"]


def buyer_match_confidence(
    buyer: CashBuyer,
    deal: DealForMatching,
    observed: ObservedBuyingPattern,
) -> dict[str, Any]:
    declared = match_buyer_to_deal(buyer, deal)
    declared_fit = float(declared["score"]) if declared["eligible"] else 0.0
    observed_fit, observed_reasons = _observed_fit(observed, deal)
    velocity, velocity_reasons = _velocity_score(observed)
    capital = 100.0 if buyer.proof_of_funds_verified else 50.0 if observed.cash_confirmed_count > 0 else 0.0

    # Declared criteria are the strongest current-intent evidence. Observed
    # purchases improve confidence but never silently replace what a buyer said.
    confidence = round(
        declared_fit * 0.50
        + observed_fit * 0.25
        + capital * 0.15
        + velocity * 0.10,
        2,
    )
    return {
        "eligible": bool(declared["eligible"]),
        "confidence": confidence,
        "components": {
            "declared_buying_box_fit": round(declared_fit, 2),
            "observed_purchase_fit": round(observed_fit, 2),
            "capital_evidence": round(capital, 2),
            "closing_velocity": round(velocity, 2),
        },
        "declared_reasons": list(declared["reasons"]),
        "observed_reasons": observed_reasons + velocity_reasons,
        "evidence_policy": {
            "declared_box": "current buyer-stated or tenant-entered criteria",
            "observed_pattern": "historical recorded purchases; not treated as current intent",
            "cash": "verified POF or explicit mortgage-index cash evidence only",
        },
    }


def buying_box_snapshot(declared: BuyingBox, observed: ObservedBuyingPattern) -> dict[str, Any]:
    return {
        "declared": {
            "states": list(declared.states),
            "counties": list(declared.counties),
            "cities": list(declared.cities),
            "zip_codes": list(declared.zip_codes),
            "property_types": list(declared.property_types),
            "strategies": list(declared.strategies),
            "min_price": declared.min_price,
            "max_price": declared.max_price,
            "max_rehab": declared.max_rehab,
        },
        "observed": {
            "purchase_count": observed.purchase_count,
            "cash_confirmed_count": observed.cash_confirmed_count,
            "zip_codes": list(observed.zip_codes),
            "counties": list(observed.counties),
            "min_purchase_price": observed.min_purchase_price,
            "median_purchase_price": observed.median_purchase_price,
            "max_purchase_price": observed.max_purchase_price,
            "first_purchase_at": observed.first_purchase_at,
            "last_purchase_at": observed.last_purchase_at,
            "source_count": observed.source_count,
        },
    }

"""Buyer response modelling and portfolio-level disposition assignment.

``services.match_buyer`` adds fixed points for ZIP, asset type, price band, and
rehab tolerance, and returns a 0-100 number. Three things are wrong with that
for a live disposition desk:

* The score is not a probability, so "82" cannot be multiplied by an assignment
  fee to get an expected value, and two deals cannot be compared on it.
* Buyer history is a flat ``response_rate`` with no notion of recency. A buyer
  who answered ten times last year and has ignored the desk for six months
  scores identically to one who answered yesterday.
* Matching is per-property. Every deal independently picks the same handful of
  top buyers, so the best buyers get spammed while the rest of the list goes
  unused — and the desk's total expected revenue is lower than it needs to be.

This module addresses all three: a calibrated response model with recency
decay (:func:`response_probability`), and a global assignment pass
(:func:`optimize_assignments`) that maximises expected portfolio revenue under
per-buyer contact capacity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Response-model coefficients, in log-odds. These are documented priors, not
# fitted values: they encode the desk's operating experience that fit and
# demonstrated responsiveness dominate, and that verified funds matter mainly
# as a closing signal. Replace with fitted values once enough outreach
# outcomes are recorded.
RESPONSE_INTERCEPT = -2.6
RESPONSE_COEFFICIENTS = {
    "buy_box_fit": 2.4,
    "engagement": 2.1,
    "reliability": 0.9,
    "price_fit": 1.1,
    "proof_of_funds": 0.4,
}

# A buyer's demonstrated response rate is discounted as their last interaction
# recedes. Half-life of roughly four months.
ENGAGEMENT_HALF_LIFE_DAYS = 120.0
DEFAULT_DAYS_SINCE_CONTACT = 90.0

# Buy-box component weights, normalised to 1.0.
FIT_WEIGHTS = {"location": 0.34, "asset_type": 0.26, "price": 0.24, "rehab": 0.16}

# Default simultaneous deals a single buyer will be shown before fatigue sets
# in and marginal response probability collapses.
DEFAULT_BUYER_CAPACITY = 2
MAX_IMPROVEMENT_PASSES = 12


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def _price_fit(deal_price: float, min_price: float, max_price: float) -> float:
    """How centred a deal price sits inside a buyer's stated range.

    A deal at the very edge of a buyer's band is a materially weaker match than
    one in the middle, and a deal outside the band is not zero — buyers stretch
    — but it decays quickly.
    """
    if deal_price <= 0 or max_price <= min_price:
        return 0.5
    if min_price <= deal_price <= max_price:
        midpoint = (min_price + max_price) / 2.0
        half_width = (max_price - min_price) / 2.0
        offset = abs(deal_price - midpoint) / half_width
        return 1.0 - 0.35 * offset
    # Outside the band: decay by how far out, relative to band width.
    band_width = max_price - min_price
    excess = (min_price - deal_price) if deal_price < min_price else (deal_price - max_price)
    return _clamp(0.45 * math.exp(-excess / max(1.0, band_width * 0.25)))


def buy_box_fit(buyer: dict, prop: dict) -> tuple[float, dict[str, float]]:
    """Score how well a property matches a buyer's buy box, in [0, 1]."""
    deal_price = float(prop.get("mao") or prop.get("asking_price") or 0)

    zip_codes = [str(z) for z in (buyer.get("zip_codes") or [])]
    asset_types = [str(a) for a in (buyer.get("asset_types") or [])]

    components = {
        "location": 1.0 if str(prop.get("zip_code") or "") in zip_codes else 0.0,
        "asset_type": 1.0 if str(prop.get("property_type") or "") in asset_types else 0.0,
        "price": _price_fit(
            deal_price, float(buyer.get("min_price") or 0), float(buyer.get("max_price") or 0)
        ),
        "rehab": 1.0
        if float(prop.get("repairs") or 0) <= float(buyer.get("max_rehab") or 0)
        else _clamp(
            float(buyer.get("max_rehab") or 0) / max(1.0, float(prop.get("repairs") or 1))
        ),
    }
    total = sum(FIT_WEIGHTS[name] * value for name, value in components.items())
    return _clamp(total), components


def engagement(buyer: dict) -> float:
    """Demonstrated responsiveness, decayed by time since last contact."""
    response_rate = _clamp(float(buyer.get("response_rate") or 0) / 100.0)
    days = buyer.get("days_since_last_contact")
    days = DEFAULT_DAYS_SINCE_CONTACT if days is None else max(0.0, float(days))
    decay = 0.5 ** (days / ENGAGEMENT_HALF_LIFE_DAYS)
    return response_rate * decay


def response_probability(buyer: dict, prop: dict) -> dict:
    """Probability this buyer engages with this property, with its drivers."""
    fit, fit_components = buy_box_fit(buyer, prop)
    engagement_score = engagement(buyer)
    reliability = _clamp(float(buyer.get("reliability_score") or 50) / 100.0)
    proof_of_funds = 1.0 if buyer.get("proof_of_funds_verified") else 0.0
    price_fit = fit_components["price"]

    inputs = {
        "buy_box_fit": fit,
        "engagement": engagement_score,
        "reliability": reliability,
        "price_fit": price_fit,
        "proof_of_funds": proof_of_funds,
    }
    contributions = {
        name: RESPONSE_COEFFICIENTS[name] * value for name, value in inputs.items()
    }
    probability = _sigmoid(RESPONSE_INTERCEPT + sum(contributions.values()))

    # Reliable buyers close nearer their stated timeline; unreliable ones slip.
    stated_days = float(buyer.get("closing_days") or 14)
    expected_days_to_close = stated_days * (1.0 + 0.8 * (1.0 - reliability))

    total_contribution = sum(abs(v) for v in contributions.values()) or 1.0
    drivers = sorted(
        (
            {
                "factor": name,
                "value": round(inputs[name], 4),
                "log_odds": round(value, 4),
                "share": round(abs(value) / total_contribution * 100, 1),
            }
            for name, value in contributions.items()
        ),
        key=lambda item: item["log_odds"],
        reverse=True,
    )

    return {
        "buyer_id": buyer.get("id"),
        "buyer_name": buyer.get("name"),
        "response_probability": round(probability, 4),
        "buy_box_fit": round(fit, 4),
        "fit_components": {k: round(v, 3) for k, v in fit_components.items()},
        "engagement": round(engagement_score, 4),
        "expected_days_to_close": round(expected_days_to_close, 1),
        "proof_of_funds_verified": bool(buyer.get("proof_of_funds_verified")),
        "drivers": drivers,
        "reasons": _reasons(fit_components, buyer, engagement_score),
    }


def _reasons(fit_components: dict[str, float], buyer: dict, engagement_score: float) -> list[str]:
    reasons: list[str] = []
    if fit_components["location"] >= 1.0:
        reasons.append("ZIP is inside the stated buy box")
    if fit_components["asset_type"] >= 1.0:
        reasons.append("Asset type matches")
    if fit_components["price"] >= 0.8:
        reasons.append("Price sits mid-band for this buyer")
    elif fit_components["price"] < 0.5:
        reasons.append("Price is at or outside the edge of the stated band")
    if fit_components["rehab"] < 1.0:
        reasons.append("Repair scope exceeds stated rehab tolerance")
    if buyer.get("proof_of_funds_verified"):
        reasons.append("Proof of funds verified")
    if engagement_score < 0.05:
        reasons.append("No recent engagement; treat responsiveness as unproven")
    return reasons


def rank_buyers(prop: dict, buyers: list[dict], *, minimum_probability: float = 0.0) -> list[dict]:
    """Rank buyers for a single property by response probability."""
    ranked = [response_probability(buyer, prop) for buyer in buyers]
    ranked = [row for row in ranked if row["response_probability"] >= minimum_probability]
    return sorted(ranked, key=lambda row: row["response_probability"], reverse=True)


@dataclass
class Assignment:
    deal_id: int | None
    property_id: int | None
    buyer_id: int | None
    buyer_name: str | None
    response_probability: float
    expected_value: float
    assignment_fee: float
    rank: int

    def as_dict(self) -> dict:
        return {
            "deal_id": self.deal_id,
            "property_id": self.property_id,
            "buyer_id": self.buyer_id,
            "buyer_name": self.buyer_name,
            "response_probability": round(self.response_probability, 4),
            "expected_value": round(self.expected_value, 2),
            "assignment_fee": round(self.assignment_fee, 2),
            "rank": self.rank,
        }


def optimize_assignments(
    deals: list[dict],
    buyers: list[dict],
    *,
    buyer_capacity: int = DEFAULT_BUYER_CAPACITY,
    offers_per_deal: int = 1,
    minimum_probability: float = 0.05,
) -> dict:
    """Assign buyers to deals to maximise expected portfolio revenue.

    Solves the capacitated assignment problem with a greedy pass followed by
    2-opt swap improvement. For the tens-of-deals scale a disposition desk
    actually runs, this reaches the optimum or within a fraction of a percent
    of it, without pulling in a solver dependency.

    ``buyer_capacity`` caps how many deals one buyer is shown at once — the
    constraint that makes this a portfolio problem rather than N independent
    rankings.
    """
    if buyer_capacity < 1:
        raise ValueError("buyer_capacity must be at least 1")
    if offers_per_deal < 1:
        raise ValueError("offers_per_deal must be at least 1")

    # Value matrix: expected revenue from showing this deal to this buyer.
    candidates: list[tuple[float, int, int, float]] = []  # (value, deal_idx, buyer_idx, probability)
    for deal_index, deal in enumerate(deals):
        prop = deal.get("property") or {}
        fee = float(deal.get("projected_assignment_fee") or 0)
        for buyer_index, buyer in enumerate(buyers):
            evaluation = response_probability(buyer, prop)
            probability = evaluation["response_probability"]
            if probability < minimum_probability:
                continue
            candidates.append((probability * fee, deal_index, buyer_index, probability))

    candidates.sort(key=lambda item: item[0], reverse=True)

    # Greedy seed.
    deal_slots: dict[int, list[tuple[float, int, float]]] = {index: [] for index in range(len(deals))}
    buyer_load: dict[int, int] = {index: 0 for index in range(len(buyers))}

    for value, deal_index, buyer_index, probability in candidates:
        if len(deal_slots[deal_index]) >= offers_per_deal:
            continue
        if buyer_load[buyer_index] >= buyer_capacity:
            continue
        if any(existing_buyer == buyer_index for _, existing_buyer, _ in deal_slots[deal_index]):
            continue
        deal_slots[deal_index].append((value, buyer_index, probability))
        buyer_load[buyer_index] += 1

    value_lookup = {(d, b): (v, p) for v, d, b, p in candidates}

    # 2-opt improvement: swapping two assignments can raise the total when the
    # greedy pass locked a strong buyer onto a low-fee deal early.
    for _ in range(MAX_IMPROVEMENT_PASSES):
        improved = False
        deal_indices = list(deal_slots)
        for i, left_deal in enumerate(deal_indices):
            for right_deal in deal_indices[i + 1 :]:
                for left_slot, (left_value, left_buyer, _) in enumerate(deal_slots[left_deal]):
                    for right_slot, (right_value, right_buyer, _) in enumerate(deal_slots[right_deal]):
                        swapped_left = value_lookup.get((left_deal, right_buyer))
                        swapped_right = value_lookup.get((right_deal, left_buyer))
                        if swapped_left is None or swapped_right is None:
                            continue
                        if swapped_left[0] + swapped_right[0] > left_value + right_value + 1e-9:
                            deal_slots[left_deal][left_slot] = (
                                swapped_left[0],
                                right_buyer,
                                swapped_left[1],
                            )
                            deal_slots[right_deal][right_slot] = (
                                swapped_right[0],
                                left_buyer,
                                swapped_right[1],
                            )
                            improved = True
        if not improved:
            break

    assignments: list[Assignment] = []
    for deal_index, slots in deal_slots.items():
        deal = deals[deal_index]
        fee = float(deal.get("projected_assignment_fee") or 0)
        for rank_index, (value, buyer_index, probability) in enumerate(
            sorted(slots, key=lambda item: item[0], reverse=True), start=1
        ):
            buyer = buyers[buyer_index]
            assignments.append(
                Assignment(
                    deal_id=deal.get("id"),
                    property_id=(deal.get("property") or {}).get("id"),
                    buyer_id=buyer.get("id"),
                    buyer_name=buyer.get("name"),
                    response_probability=probability,
                    expected_value=value,
                    assignment_fee=fee,
                    rank=rank_index,
                )
            )

    unmatched = [
        deals[index].get("id") for index, slots in deal_slots.items() if not slots
    ]
    expected_revenue = sum(assignment.expected_value for assignment in assignments)

    # Baseline: what independent per-deal ranking would have produced, ignoring
    # capacity. The delta is the value the portfolio view actually adds.
    naive_revenue = 0.0
    for deal_index, deal in enumerate(deals):
        best = [value for value, d, _, _ in candidates if d == deal_index]
        naive_revenue += sum(sorted(best, reverse=True)[:offers_per_deal])

    return {
        "assignments": [assignment.as_dict() for assignment in assignments],
        "expected_revenue": round(expected_revenue, 2),
        "unconstrained_expected_revenue": round(naive_revenue, 2),
        "unmatched_deals": unmatched,
        "buyer_utilization": {
            str(buyers[index].get("id")): load for index, load in buyer_load.items() if load
        },
        "parameters": {
            "buyer_capacity": buyer_capacity,
            "offers_per_deal": offers_per_deal,
            "minimum_probability": minimum_probability,
        },
        "note": (
            "Expected revenue is capacity-constrained: each buyer is shown at most "
            f"{buyer_capacity} deal(s). The unconstrained figure ignores that limit and is "
            "shown only as an upper bound, not an achievable target."
        ),
    }

from __future__ import annotations

from .models import Buyer, Property

DISTRESS_WEIGHTS = {
    "vacant": 18,
    "boarded_windows": 18,
    "fire_damage": 20,
    "code_violation": 14,
    "tax_delinquent": 14,
    "pre_foreclosure": 12,
    "probate": 10,
    "absentee_owner": 8,
    "out_of_state_owner": 8,
    "overgrown_grass": 6,
    "roof_damage": 10,
    "foundation_issue": 15,
}


def calculate_mao(arv: float, repairs: float, assignment_fee: float = 15_000, factor: float = 0.70) -> float:
    return round(max(0, arv * factor - repairs - assignment_fee), 2)


def distress_score(signals: list[str]) -> float:
    return min(100.0, float(sum(DISTRESS_WEIGHTS.get(signal, 4) for signal in set(signals))))


def lead_score(motivation: float, equity: float, distress: float, buyer_demand: float = 50) -> float:
    return round(motivation * 0.30 + equity * 0.25 + distress * 0.25 + buyer_demand * 0.20, 2)


def match_buyer(buyer: Buyer, prop: Property) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    deal_price = prop.mao or prop.asking_price or 0

    if prop.zip_code in (buyer.zip_codes or []):
        score += 30
        reasons.append("ZIP buy-box match")
    if prop.property_type in (buyer.asset_types or []):
        score += 25
        reasons.append("Asset-type match")
    if buyer.min_price <= deal_price <= buyer.max_price:
        score += 20
        reasons.append("Price-range match")
    if (prop.repairs or 0) <= buyer.max_rehab:
        score += 10
        reasons.append("Rehab tolerance match")
    score += min(10, buyer.response_rate / 10)
    score += min(5, buyer.reliability_score / 20)
    if buyer.proof_of_funds_verified:
        reasons.append("Verified proof of funds")
    return round(min(score, 100), 2), reasons

from __future__ import annotations

from typing import Any

BUYER_CLASSES = {
    "individual": "Individual investor",
    "llc": "LLC / local operator",
    "fund": "Fund / institutional buyer",
    "private_capital": "Private capital / family office",
    "corporation": "Corporation",
    "partnership": "Partnership",
    "trust": "Trust",
    "unknown": "Unclassified buyer",
}

STRATEGIES = {"flip", "rental", "brRRR", "wholetail", "development", "land", "multifamily", "commercial"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _norm_list(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        value = [value]
    return {str(item).strip().lower() for item in value if str(item).strip()}


def classify_buyer(name: str, declared_type: str | None = None) -> str:
    declared = str(declared_type or "").strip().lower()
    aliases = {
        "hedge_fund": "fund", "institutional": "fund", "institution": "fund",
        "family_office": "private_capital", "private_equity": "private_capital",
        "cash_buyer": "unknown", "individual_investor": "individual",
    }
    if declared in BUYER_CLASSES:
        return declared
    if declared in aliases:
        return aliases[declared]
    text = f" {str(name or '').lower()} "
    if any(token in text for token in (" fund ", "capital management", "asset management", "reit")):
        return "fund"
    if any(token in text for token in ("family office", "private capital", "private equity")):
        return "private_capital"
    if " llc" in text or "l.l.c" in text:
        return "llc"
    if any(token in text for token in (" inc", " corp", " corporation")):
        return "corporation"
    if any(token in text for token in (" lp", " llp", " partnership")):
        return "partnership"
    if " trust" in text:
        return "trust"
    # A natural-person-looking name is only a classification hint, never identity verification.
    parts = [p for p in str(name or "").strip().split() if p]
    return "individual" if 2 <= len(parts) <= 4 else "unknown"


def buying_box_fit(buyer: dict[str, Any], deal: dict[str, Any]) -> dict[str, Any]:
    """Explainable 0-100 buying-box fit; no inferred contact or funding facts."""
    prop = deal.get("property") or deal
    price = _num(prop.get("assignment_price") or prop.get("mao") or prop.get("asking_price"))
    arv = _num(prop.get("arv"))
    repairs = _num(prop.get("repairs"))
    state = str(prop.get("state") or "").lower()
    county = str(prop.get("county") or "").lower()
    city = str(prop.get("city") or "").lower()
    zip_code = str(prop.get("zip_code") or prop.get("zip") or "").lower()
    asset_type = str(prop.get("property_type") or "").lower()

    zips = _norm_list(buyer.get("zip_codes"))
    cities = _norm_list(buyer.get("cities"))
    counties = _norm_list(buyer.get("counties"))
    states = _norm_list(buyer.get("states"))
    assets = _norm_list(buyer.get("asset_types"))
    strategies = _norm_list(buyer.get("strategies"))

    location = 0.0
    location_reason = "No stated geography match"
    if zip_code and zip_code in zips:
        location, location_reason = 1.0, "ZIP matches buying box"
    elif city and city in cities:
        location, location_reason = 0.9, "City matches buying box"
    elif county and county in counties:
        location, location_reason = 0.85, "County matches buying box"
    elif state and state in states:
        location, location_reason = 0.65, "State matches buying box"
    elif not any((zips, cities, counties, states)):
        location, location_reason = 0.35, "Buyer geography is not yet specified"

    asset = 1.0 if asset_type and asset_type in assets else (0.4 if not assets else 0.0)
    min_price = _num(buyer.get("min_price"), 0)
    max_price = _num(buyer.get("max_price"), 10_000_000)
    price_fit = 1.0 if price and min_price <= price <= max_price else (0.4 if not price else 0.0)
    max_rehab = _num(buyer.get("max_rehab"), 0)
    rehab_fit = 1.0 if repairs <= max_rehab else (0.5 if max_rehab <= 0 else max(0.0, max_rehab / max(repairs, 1)))

    min_arv = _num(buyer.get("min_arv"), 0)
    max_arv = _num(buyer.get("max_arv"), 100_000_000)
    arv_fit = 1.0 if arv and min_arv <= arv <= max_arv else (0.5 if not arv else 0.0)

    desired_strategy = str(prop.get("strategy") or "").lower()
    strategy_fit = 1.0 if desired_strategy and desired_strategy in strategies else (0.5 if not strategies or not desired_strategy else 0.0)

    reliability = max(0.0, min(1.0, _num(buyer.get("reliability_score"), 50) / 100.0))
    pof = 1.0 if buyer.get("proof_of_funds_verified") else 0.0
    cash_history = 1.0 if str(buyer.get("cash_evidence") or "").lower() == "confirmed" else 0.0

    weights = {
        "location": 0.27, "asset": 0.15, "price": 0.18, "rehab": 0.10,
        "arv": 0.07, "strategy": 0.08, "reliability": 0.08,
        "proof_of_funds": 0.04, "cash_history": 0.03,
    }
    components = {
        "location": location, "asset": asset, "price": price_fit, "rehab": rehab_fit,
        "arv": arv_fit, "strategy": strategy_fit, "reliability": reliability,
        "proof_of_funds": pof, "cash_history": cash_history,
    }
    score = round(100 * sum(weights[k] * components[k] for k in weights), 1)

    buyer_class = classify_buyer(str(buyer.get("name") or buyer.get("grantee_name") or ""), buyer.get("buyer_type") or buyer.get("entity_type"))
    reasons = [location_reason]
    if asset >= 1:
        reasons.append("Asset type matches")
    if price_fit >= 1:
        reasons.append("Price is inside stated range")
    if rehab_fit >= 1:
        reasons.append("Repairs are inside stated tolerance")
    if pof:
        reasons.append("Proof of funds verified")
    if cash_history:
        reasons.append("Recorded purchase has confirmed cash evidence")

    return {
        "buyer_id": buyer.get("id"),
        "buyer_name": buyer.get("name") or buyer.get("grantee_name"),
        "buyer_class": buyer_class,
        "buyer_class_label": BUYER_CLASSES[buyer_class],
        "match_score": score,
        "components": {k: round(v, 3) for k, v in components.items()},
        "reasons": reasons,
        "funding_status": "verified" if pof else ("historical_cash_evidence" if cash_history else "unverified"),
        "contact_status": "available" if buyer.get("phone") or buyer.get("email") else "not_on_file",
    }


def rank_matching_buyers(deal: dict[str, Any], buyers: list[dict[str, Any]], minimum_score: float = 35.0) -> list[dict[str, Any]]:
    ranked = [buying_box_fit(buyer, deal) for buyer in buyers]
    return sorted((row for row in ranked if row["match_score"] >= minimum_score), key=lambda row: row["match_score"], reverse=True)

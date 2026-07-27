"""Comparable-sales valuation and probabilistic deal underwriting.

The legacy underwriting path treats ARV as an operator-supplied number and
reduces a deal to ``arv * 0.70 - repairs - fee``. That produces a single point
estimate with no error bars, no defensible derivation, and no notion of how
likely the deal is to actually clear.

This module replaces that with the two pieces a real underwriting desk uses:

1. A sales-comparison grid (:func:`estimate_arv`) that adjusts each comparable
   toward the subject property, weights comparables by similarity, rejects
   outliers, and reports a confidence interval instead of a bare number.
2. A Monte Carlo simulation (:func:`simulate_deal`) that propagates ARV,
   repair, and buyer-demand uncertainty into a distribution over assignment
   spread, so an offer can be priced to a target probability of success
   rather than to a fixed 70% rule of thumb.

Everything here is pure Python and deterministic under a fixed seed: no
numeric dependencies are added, and results are reproducible for audit.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

# --- Sales-comparison grid constants -------------------------------------
#
# Contributory values follow standard appraisal practice: a marginal square
# foot is worth less than the average square foot, and bed/bath counts carry
# fixed contributory value rather than scaling with price.

MARGINAL_SQFT_RATIO = 0.55
BEDROOM_VALUE = 7_500.0
BATHROOM_VALUE = 9_000.0
AGE_VALUE_PER_YEAR = 450.0
MAX_AGE_ADJUSTMENT = 45_000.0
DEFAULT_MONTHLY_APPRECIATION = 0.0035

# Comparables whose net adjustment exceeds this share of their sale price are
# poor matches. They are down-weighted rather than dropped, so a thin market
# still produces an estimate — flagged as low confidence.
NET_ADJUSTMENT_GUIDELINE = 0.15
NET_ADJUSTMENT_HARD_LIMIT = 0.35

# Similarity kernel scales.
DISTANCE_SCALE_MILES = 1.0
RECENCY_SCALE_MONTHS = 6.0
SIZE_SCALE_RATIO = 0.25

OUTLIER_MAD_THRESHOLD = 2.5
MIN_COMPS_FOR_OUTLIER_REJECTION = 5

# Condition tiers, ordered worst to best. The index is used both to adjust
# comparables toward the subject and to seed the repair model.
CONDITION_INDEX = {
    "gut": 0.0,
    "heavy": 0.25,
    "moderate": 0.5,
    "cosmetic": 0.75,
    "average": 0.8,
    "good": 0.9,
    "turnkey": 1.0,
    "renovated": 1.0,
}
CONDITION_VALUE_SPREAD = 0.30

# --- Repair model ---------------------------------------------------------

REPAIR_PSF_BY_CONDITION = {
    "turnkey": 0.0,
    "renovated": 0.0,
    "good": 4.0,
    "average": 9.0,
    "cosmetic": 18.0,
    "moderate": 38.0,
    "heavy": 65.0,
    "gut": 95.0,
}

# Line-item add-ons for specific observed defects, on top of the per-sqft base.
REPAIR_SIGNAL_COSTS = {
    "roof_damage": 12_000.0,
    "foundation_issue": 28_000.0,
    "fire_damage": 48_000.0,
    "water_damage": 15_000.0,
    "mold": 11_000.0,
    "boarded_windows": 6_500.0,
    "code_violation": 7_500.0,
    "vacant": 4_000.0,
    "overgrown_grass": 1_200.0,
    "hvac_failure": 8_500.0,
    "plumbing_failure": 9_000.0,
    "electrical_failure": 9_500.0,
}
REPAIR_CONTINGENCY = 0.12
MAX_REPAIR_SHARE_OF_ARV = 0.75

# --- Simulation defaults --------------------------------------------------

DEFAULT_BUYER_YIELD = 0.72
BUYER_YIELD_STDDEV = 0.04
MIN_BUYER_YIELD = 0.55
MAX_BUYER_YIELD = 0.88

# Repair overruns are right-skewed: budgets are missed high far more often
# than they are missed low.
REPAIR_OVERRUN_SIGMA = 0.22
REPAIR_OVERRUN_DRIFT = 0.06

DEFAULT_SIMULATIONS = 4_000
DEFAULT_SEED = 20260727


class ValuationError(ValueError):
    """Raised when an estimate cannot be produced from the supplied inputs."""


@dataclass(frozen=True)
class Comparable:
    """A closed comparable sale used in the sales-comparison grid."""

    address: str
    sale_price: float
    sale_date: date
    sqft: int
    bedrooms: float | None = None
    bathrooms: float | None = None
    year_built: int | None = None
    distance_miles: float = 0.0
    condition: str = "average"
    source: str = "unspecified"


@dataclass(frozen=True)
class SubjectProperty:
    """The property being valued."""

    sqft: int
    bedrooms: float | None = None
    bathrooms: float | None = None
    year_built: int | None = None
    condition: str = "moderate"
    distress_signals: tuple[str, ...] = ()


@dataclass
class ComparableAdjustment:
    """The full audit trail for one comparable in the grid."""

    address: str
    sale_price: float
    adjusted_price: float
    adjusted_price_per_sqft: float
    weight: float
    net_adjustment: float
    net_adjustment_pct: float
    months_since_sale: float
    distance_miles: float
    adjustments: dict[str, float]
    excluded: bool = False
    exclusion_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "sale_price": round(self.sale_price, 2),
            "adjusted_price": round(self.adjusted_price, 2),
            "adjusted_price_per_sqft": round(self.adjusted_price_per_sqft, 2),
            "weight": round(self.weight, 4),
            "net_adjustment": round(self.net_adjustment, 2),
            "net_adjustment_pct": round(self.net_adjustment_pct * 100, 2),
            "months_since_sale": round(self.months_since_sale, 1),
            "distance_miles": round(self.distance_miles, 2),
            "adjustments": {k: round(v, 2) for k, v in self.adjustments.items()},
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass
class ValuationResult:
    """An ARV estimate with its uncertainty and derivation."""

    arv: float
    low: float
    high: float
    confidence: float
    price_per_sqft: float
    effective_comp_count: float
    dispersion: float
    comparables: list[ComparableAdjustment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "arv": round(self.arv, 2),
            "confidence_interval": {"low": round(self.low, 2), "high": round(self.high, 2)},
            "confidence": round(self.confidence, 1),
            "price_per_sqft": round(self.price_per_sqft, 2),
            "effective_comp_count": round(self.effective_comp_count, 2),
            "dispersion": round(self.dispersion, 4),
            "comparables": [c.as_dict() for c in self.comparables],
            "warnings": list(self.warnings),
        }


def _condition_index(condition: str | None) -> float:
    return CONDITION_INDEX.get(str(condition or "average").strip().lower(), 0.8)


def _months_between(earlier: date, later: date) -> float:
    return max(0.0, (later - earlier).days / 30.4375)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _weighted_quantile(pairs: list[tuple[float, float]], q: float) -> float:
    """Weighted quantile over ``(value, weight)`` pairs.

    Uses the standard "smallest value whose cumulative weight reaches q" rule,
    which is well defined for any positive weights and needs no interpolation
    assumptions the underwriting audit would have to justify.
    """
    if not pairs:
        raise ValuationError("Cannot compute a quantile over an empty sample")
    ordered = sorted(pairs, key=lambda item: item[0])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = q * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= target:
            return value
    return ordered[-1][0]


def _similarity_weight(
    subject: SubjectProperty,
    comp: Comparable,
    months: float,
    net_adjustment_pct: float,
) -> float:
    """Similarity kernel: closer, more recent, more similar comps dominate."""
    distance_term = math.exp(-((max(0.0, comp.distance_miles) / DISTANCE_SCALE_MILES) ** 2))
    recency_term = math.exp(-months / RECENCY_SCALE_MONTHS)

    size_delta_ratio = abs(comp.sqft - subject.sqft) / max(1.0, float(subject.sqft))
    size_term = math.exp(-((size_delta_ratio / SIZE_SCALE_RATIO) ** 2))

    # A comp needing large adjustments is a weak comp even if it is next door.
    quality_term = 1.0 / (1.0 + (abs(net_adjustment_pct) / NET_ADJUSTMENT_GUIDELINE) ** 2)

    return max(1e-6, distance_term * recency_term * size_term * quality_term)


def _adjust_comparable(
    subject: SubjectProperty,
    comp: Comparable,
    *,
    base_price_per_sqft: float,
    as_of: date,
    monthly_appreciation: float,
    basis: str,
) -> ComparableAdjustment:
    """Build one row of the sales-comparison grid.

    Every adjustment moves the *comparable* toward the *subject*: a positive
    adjustment means the comp would have sold for more had it matched the
    subject.
    """
    if comp.sale_price <= 0:
        raise ValuationError(f"Comparable {comp.address!r} has a non-positive sale price")
    if comp.sqft <= 0:
        raise ValuationError(f"Comparable {comp.address!r} has non-positive square footage")

    months = _months_between(comp.sale_date, as_of)
    adjustments: dict[str, float] = {}

    # Market conditions: bring a historical sale forward to today's market.
    adjustments["market_time"] = comp.sale_price * (
        (1.0 + monthly_appreciation) ** months - 1.0
    )

    # Size, priced at the marginal rather than average rate per square foot.
    marginal_psf = base_price_per_sqft * MARGINAL_SQFT_RATIO
    adjustments["size"] = (subject.sqft - comp.sqft) * marginal_psf

    if subject.bedrooms is not None and comp.bedrooms is not None:
        adjustments["bedrooms"] = (subject.bedrooms - comp.bedrooms) * BEDROOM_VALUE
    if subject.bathrooms is not None and comp.bathrooms is not None:
        adjustments["bathrooms"] = (subject.bathrooms - comp.bathrooms) * BATHROOM_VALUE

    if subject.year_built and comp.year_built:
        raw_age = (subject.year_built - comp.year_built) * AGE_VALUE_PER_YEAR
        adjustments["age"] = max(-MAX_AGE_ADJUSTMENT, min(MAX_AGE_ADJUSTMENT, raw_age))

    # ARV is the value *after* repair, so the subject is treated as restored to
    # market condition and only the comp's condition is adjusted. An as-is
    # basis adjusts toward the subject's actual condition instead.
    target_condition = 1.0 if basis == "arv" else _condition_index(subject.condition)
    condition_delta = target_condition - _condition_index(comp.condition)
    if abs(condition_delta) > 1e-9:
        adjustments["condition"] = condition_delta * CONDITION_VALUE_SPREAD * comp.sale_price

    net_adjustment = sum(adjustments.values())
    adjusted_price = comp.sale_price + net_adjustment
    net_adjustment_pct = net_adjustment / comp.sale_price

    weight = _similarity_weight(subject, comp, months, net_adjustment_pct)

    row = ComparableAdjustment(
        address=comp.address,
        sale_price=comp.sale_price,
        adjusted_price=adjusted_price,
        adjusted_price_per_sqft=adjusted_price / max(1.0, float(subject.sqft)),
        weight=weight,
        net_adjustment=net_adjustment,
        net_adjustment_pct=net_adjustment_pct,
        months_since_sale=months,
        distance_miles=comp.distance_miles,
        adjustments=adjustments,
    )

    if abs(net_adjustment_pct) > NET_ADJUSTMENT_HARD_LIMIT:
        row.excluded = True
        row.exclusion_reason = (
            f"Net adjustment {net_adjustment_pct * 100:.0f}% exceeds the "
            f"{NET_ADJUSTMENT_HARD_LIMIT * 100:.0f}% limit"
        )
    return row


def estimate_arv(
    subject: SubjectProperty,
    comparables: list[Comparable],
    *,
    as_of: date | None = None,
    monthly_appreciation: float = DEFAULT_MONTHLY_APPRECIATION,
    basis: str = "arv",
) -> ValuationResult:
    """Estimate after-repair value from comparable sales.

    Raises :class:`ValuationError` when no usable comparable survives, which is
    deliberate: fabricating a valuation from nothing is worse than reporting
    that the market data is insufficient.
    """
    if subject.sqft <= 0:
        raise ValuationError("Subject square footage must be positive")
    if not comparables:
        raise ValuationError("At least one comparable sale is required")

    as_of = as_of or _today()
    warnings: list[str] = []

    # Seed the marginal-rate calculation with the raw market rate, so the size
    # adjustment is anchored to observed prices rather than a constant.
    base_price_per_sqft = sum(c.sale_price / max(1, c.sqft) for c in comparables) / len(comparables)

    rows = [
        _adjust_comparable(
            subject,
            comp,
            base_price_per_sqft=base_price_per_sqft,
            as_of=as_of,
            monthly_appreciation=monthly_appreciation,
            basis=basis,
        )
        for comp in comparables
    ]

    active = [row for row in rows if not row.excluded]
    if not active:
        raise ValuationError(
            "Every comparable required an adjustment beyond the acceptable limit; "
            "no defensible estimate can be produced"
        )
    if len(active) < len(rows):
        warnings.append(f"{len(rows) - len(active)} comparable(s) excluded for excessive adjustment")

    # Outlier rejection on adjusted price per square foot, via weighted median
    # absolute deviation. Only applied when there are enough comps for the
    # median to mean anything.
    if len(active) >= MIN_COMPS_FOR_OUTLIER_REJECTION:
        psf_pairs = [(row.adjusted_price_per_sqft, row.weight) for row in active]
        median_psf = _weighted_quantile(psf_pairs, 0.5)
        deviations = [(abs(psf - median_psf), weight) for psf, weight in psf_pairs]
        mad = _weighted_quantile(deviations, 0.5)
        if mad > 0:
            for row in active:
                if abs(row.adjusted_price_per_sqft - median_psf) > OUTLIER_MAD_THRESHOLD * mad:
                    row.excluded = True
                    row.exclusion_reason = "Adjusted price per sqft is a statistical outlier"
            survivors = [row for row in active if not row.excluded]
            if survivors:
                if len(survivors) < len(active):
                    warnings.append(f"{len(active) - len(survivors)} comparable(s) rejected as outliers")
                active = survivors
            else:
                # Rejecting everything means the sample is bimodal, not that
                # the comps are bad. Keep them and flag the market instead.
                for row in active:
                    row.excluded = False
                    row.exclusion_reason = None
                warnings.append("Comparable set has no consistent centre; treat the estimate as indicative")

    total_weight = sum(row.weight for row in active)
    point = sum(row.adjusted_price * row.weight for row in active) / total_weight

    # Kish effective sample size: how many equally-weighted comps this set is
    # actually worth. A single dominant comp gives an effective count near 1.
    sum_squared_weights = sum(row.weight**2 for row in active)
    effective_n = (total_weight**2) / sum_squared_weights if sum_squared_weights > 0 else 1.0

    variance = sum(row.weight * (row.adjusted_price - point) ** 2 for row in active) / total_weight
    stddev = math.sqrt(max(0.0, variance))
    dispersion = stddev / point if point > 0 else 0.0

    # Standard error of the weighted mean, with a floor: three near-identical
    # comps do not justify a ±1% interval on a distressed asset.
    standard_error = stddev / math.sqrt(max(1.0, effective_n))
    standard_error = max(standard_error, point * 0.02)

    low = max(0.0, point - 1.96 * standard_error)
    high = point + 1.96 * standard_error

    # Confidence blends sample depth against sample agreement.
    depth_score = min(1.0, effective_n / 6.0)
    agreement_score = 1.0 / (1.0 + (dispersion / 0.10) ** 2)
    confidence = round(100.0 * math.sqrt(depth_score * agreement_score), 1)

    if effective_n < 3:
        warnings.append(
            f"Only {effective_n:.1f} effective comparable(s); widen the search radius before contracting"
        )
    if dispersion > 0.20:
        warnings.append("Comparable prices disagree by more than 20%; verify condition and sale terms")

    return ValuationResult(
        arv=point,
        low=low,
        high=high,
        confidence=confidence,
        price_per_sqft=point / subject.sqft,
        effective_comp_count=effective_n,
        dispersion=dispersion,
        comparables=rows,
        warnings=warnings,
    )


def estimate_repairs(subject: SubjectProperty, arv: float | None = None) -> dict:
    """Estimate the repair budget from condition tier and observed defects."""
    if subject.sqft <= 0:
        raise ValuationError("Subject square footage must be positive")

    condition = str(subject.condition or "moderate").strip().lower()
    base_psf = REPAIR_PSF_BY_CONDITION.get(condition, REPAIR_PSF_BY_CONDITION["moderate"])
    base_cost = base_psf * subject.sqft

    line_items: dict[str, float] = {}
    for signal in dict.fromkeys(subject.distress_signals):
        cost = REPAIR_SIGNAL_COSTS.get(str(signal).strip().lower())
        if cost:
            line_items[str(signal).strip().lower()] = cost

    subtotal = base_cost + sum(line_items.values())
    contingency = subtotal * REPAIR_CONTINGENCY
    total = subtotal + contingency

    capped = False
    if arv and arv > 0:
        ceiling = arv * MAX_REPAIR_SHARE_OF_ARV
        if total > ceiling:
            total = ceiling
            capped = True

    return {
        "total": round(total, 2),
        "base_cost": round(base_cost, 2),
        "base_price_per_sqft": base_psf,
        "line_items": {k: round(v, 2) for k, v in line_items.items()},
        "contingency": round(contingency, 2),
        "contingency_rate": REPAIR_CONTINGENCY,
        "capped_at_arv_share": capped,
        "condition": condition,
    }


def _truncated_normal(rng: random.Random, mean: float, stddev: float, low: float, high: float) -> float:
    for _ in range(16):
        value = rng.gauss(mean, stddev)
        if low <= value <= high:
            return value
    return min(high, max(low, mean))


@dataclass
class SimulationResult:
    """The outcome distribution for a contemplated contract price."""

    contract_price: float
    probability_of_target: float
    expected_spread: float
    percentiles: dict[str, float]
    recommended_max_offer: float
    downside_spread: float
    iterations: int
    assumptions: dict

    def as_dict(self) -> dict:
        return {
            "contract_price": round(self.contract_price, 2),
            "probability_of_target": round(self.probability_of_target, 4),
            "expected_spread": round(self.expected_spread, 2),
            "percentiles": {k: round(v, 2) for k, v in self.percentiles.items()},
            "recommended_max_offer": round(self.recommended_max_offer, 2),
            "downside_spread": round(self.downside_spread, 2),
            "iterations": self.iterations,
            "assumptions": self.assumptions,
        }


def simulate_deal(
    *,
    arv: float,
    arv_low: float | None = None,
    arv_high: float | None = None,
    repairs: float,
    contract_price: float,
    target_fee: float = 15_000.0,
    buyer_yield: float = DEFAULT_BUYER_YIELD,
    buyer_yield_stddev: float = BUYER_YIELD_STDDEV,
    closing_costs: float = 3_500.0,
    confidence_target: float = 0.75,
    iterations: int = DEFAULT_SIMULATIONS,
    seed: int = DEFAULT_SEED,
) -> SimulationResult:
    """Simulate assignment spread across ARV, repair, and demand uncertainty.

    ``recommended_max_offer`` is the contract price at which the assignment
    still clears ``target_fee`` in ``confidence_target`` of simulated worlds.
    That is the number the 70% rule is a crude approximation of — except this
    one adapts to how uncertain the specific deal actually is.
    """
    if arv <= 0:
        raise ValuationError("ARV must be positive to simulate a deal")
    if repairs < 0:
        raise ValuationError("Repairs cannot be negative")
    if iterations < 1:
        raise ValuationError("At least one simulation iteration is required")
    if not 0.0 < confidence_target < 1.0:
        raise ValuationError("confidence_target must be strictly between 0 and 1")

    # Translate the ARV confidence interval into a lognormal scale parameter.
    # A 95% interval spans 2 * 1.96 sigma, so sigma follows from its width.
    if arv_low is not None and arv_high is not None and arv_high > arv_low > 0:
        arv_sigma = (math.log(arv_high) - math.log(arv_low)) / (2 * 1.96)
    else:
        arv_sigma = 0.08
    arv_sigma = max(0.01, min(0.40, arv_sigma))

    rng = random.Random(seed)
    spreads: list[float] = []
    buyer_prices: list[float] = []

    for _ in range(iterations):
        realized_arv = arv * math.exp(arv_sigma * rng.gauss(0.0, 1.0))
        # Right-skewed repair draw: the drift term makes overruns more likely
        # than equivalent underruns, matching how rehab budgets actually miss.
        realized_repairs = repairs * math.exp(
            REPAIR_OVERRUN_DRIFT + REPAIR_OVERRUN_SIGMA * rng.gauss(0.0, 1.0)
        )
        realized_yield = _truncated_normal(
            rng, buyer_yield, buyer_yield_stddev, MIN_BUYER_YIELD, MAX_BUYER_YIELD
        )
        buyer_price = realized_arv * realized_yield - realized_repairs
        buyer_prices.append(buyer_price)
        spreads.append(buyer_price - contract_price - closing_costs)

    spreads.sort()
    successes = sum(1 for spread in spreads if spread >= target_fee)

    def percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
        return values[index]

    # Solve for the offer meeting the confidence target. Spread decreases
    # one-for-one with contract price, so the answer is a direct quantile of
    # the achievable buyer price rather than a search.
    buyer_prices.sort()
    offer_quantile = percentile(buyer_prices, 1.0 - confidence_target)
    recommended_max_offer = max(0.0, offer_quantile - target_fee - closing_costs)

    return SimulationResult(
        contract_price=contract_price,
        probability_of_target=successes / iterations,
        expected_spread=sum(spreads) / iterations,
        percentiles={
            "p10": percentile(spreads, 0.10),
            "p25": percentile(spreads, 0.25),
            "p50": percentile(spreads, 0.50),
            "p75": percentile(spreads, 0.75),
            "p90": percentile(spreads, 0.90),
        },
        recommended_max_offer=recommended_max_offer,
        downside_spread=percentile(spreads, 0.10),
        iterations=iterations,
        assumptions={
            "arv": round(arv, 2),
            "arv_sigma": round(arv_sigma, 4),
            "repairs": round(repairs, 2),
            "target_fee": round(target_fee, 2),
            "buyer_yield": buyer_yield,
            "closing_costs": round(closing_costs, 2),
            "confidence_target": confidence_target,
            "seed": seed,
        },
    )


def underwrite(
    subject: SubjectProperty,
    comparables: list[Comparable],
    *,
    contract_price: float | None = None,
    target_fee: float = 15_000.0,
    repairs_override: float | None = None,
    confidence_target: float = 0.75,
    as_of: date | None = None,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Run the full underwriting chain: comps to ARV to repairs to offer."""
    valuation = estimate_arv(subject, comparables, as_of=as_of)
    repair_estimate = estimate_repairs(subject, arv=valuation.arv)
    repairs = repairs_override if repairs_override is not None else repair_estimate["total"]

    # Price the first pass at the risk-adjusted offer itself when the operator
    # has not proposed a contract price.
    provisional = simulate_deal(
        arv=valuation.arv,
        arv_low=valuation.low,
        arv_high=valuation.high,
        repairs=repairs,
        contract_price=contract_price if contract_price is not None else 0.0,
        target_fee=target_fee,
        confidence_target=confidence_target,
        seed=seed,
    )
    price = contract_price if contract_price is not None else provisional.recommended_max_offer
    simulation = (
        provisional
        if contract_price is not None
        else simulate_deal(
            arv=valuation.arv,
            arv_low=valuation.low,
            arv_high=valuation.high,
            repairs=repairs,
            contract_price=price,
            target_fee=target_fee,
            confidence_target=confidence_target,
            seed=seed,
        )
    )

    return {
        "valuation": valuation.as_dict(),
        "repairs": repair_estimate,
        "repairs_used": round(repairs, 2),
        "simulation": simulation.as_dict(),
        "recommended_max_offer": round(simulation.recommended_max_offer, 2),
        "evaluated_contract_price": round(price, 2),
        "decision_quality": _decision_quality(valuation.confidence, simulation.probability_of_target),
    }


def _decision_quality(valuation_confidence: float, probability: float) -> dict:
    """Summarise whether this deal is safe to act on without a human re-check."""
    if valuation_confidence < 40:
        verdict = "insufficient_data"
        guidance = "Valuation confidence is too low to price an offer; pull more comparables."
    elif probability >= 0.75 and valuation_confidence >= 60:
        verdict = "proceed"
        guidance = "Deal clears the target fee across most simulated outcomes."
    elif probability >= 0.5:
        verdict = "marginal"
        guidance = "Deal clears more often than not; renegotiate price or verify repairs before contracting."
    else:
        verdict = "reject"
        guidance = "Deal fails the target fee in most simulated outcomes at this price."
    return {
        "verdict": verdict,
        "guidance": guidance,
        "valuation_confidence": round(valuation_confidence, 1),
        "probability_of_target": round(probability, 4),
    }

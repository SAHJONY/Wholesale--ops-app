"""Pipeline conversion, revenue forecasting, and bottleneck detection.

``operating_system.executive_brief`` reports projected revenue as the raw sum
of ``projected_assignment_fee`` across every deal that is not closed or dead.
That figure counts a lead nobody has called and a deal awaiting funding as
worth exactly the same, so it systematically overstates the pipeline and
cannot be used for planning.

This module produces a forecast that accounts for where each deal actually is:

* **Beta-smoothed stage conversion.** Transition rates are estimated from
  observed history with a documented prior, so a stage with two observations
  does not report a 100% or 0% conversion rate.
* **Expected-value forecasting.** Each deal is discounted by its probability of
  reaching close from its current stage, and the aggregate carries an interval
  derived from the variance of the underlying Bernoulli outcomes.
* **Bottleneck and stall detection.** Identifies where value is accumulating
  without moving, which is the actionable form of the same data.

Pure Python and deterministic.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# The canonical funnel. Deals in stages outside this list are counted as active
# but excluded from stage-conversion maths rather than silently coerced.
FUNNEL = ("lead", "nurture", "qualified", "contracted", "assigned", "closing", "closed")
TERMINAL_STAGES = {"closed", "dead"}

# Beta prior on each stage transition. Chosen to be weak but not flat: it
# encodes "most deals do not advance" without overwhelming real observations.
# Equivalent to having seen ~4 prior attempts at a 35% rate.
PRIOR_ALPHA = 1.4
PRIOR_BETA = 2.6

# A deal sitting more than this multiple of its stage's typical dwell time is
# treated as stalled.
STALL_MULTIPLIER = 2.0
MIN_STALL_DAYS = 14.0

# Fallback dwell times (days) per stage, used when history is too thin to
# measure. Derived from the closing timeline the offer terms already assume.
DEFAULT_DWELL_DAYS = {
    "lead": 5.0,
    "nurture": 30.0,
    "qualified": 10.0,
    "contracted": 7.0,
    "assigned": 7.0,
    "closing": 21.0,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _days_since(value: datetime | None) -> float | None:
    moment = _as_utc(value)
    if moment is None:
        return None
    return max(0.0, (_now() - moment).total_seconds() / 86400.0)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def stage_index(stage: str) -> int | None:
    try:
        return FUNNEL.index(str(stage or "").strip().lower())
    except ValueError:
        return None


def estimate_conversion_rates(history: list[dict]) -> dict[str, dict]:
    """Estimate per-stage advance probability from historical deals.

    ``history`` holds resolved deals: each needs a ``furthest_stage`` (the
    deepest stage the deal ever reached) and an ``outcome`` of ``closed`` or
    ``dead``. A deal that died at ``qualified`` counts as an attempt at the
    qualified→contracted transition and a failure; one that closed counts as a
    success at every transition it passed through.
    """
    attempts = {stage: 0 for stage in FUNNEL[:-1]}
    successes = {stage: 0 for stage in FUNNEL[:-1]}

    for record in history:
        furthest = stage_index(record.get("furthest_stage") or "")
        if furthest is None:
            continue
        closed = str(record.get("outcome") or "").strip().lower() == "closed"
        reached = len(FUNNEL) - 1 if closed else furthest

        for index, stage in enumerate(FUNNEL[:-1]):
            if index > reached:
                break
            attempts[stage] += 1
            if index < reached:
                successes[stage] += 1

    rates: dict[str, dict] = {}
    for stage in FUNNEL[:-1]:
        n = attempts[stage]
        s = successes[stage]
        posterior_mean = (s + PRIOR_ALPHA) / (n + PRIOR_ALPHA + PRIOR_BETA)
        # Variance of a Beta posterior, for reporting how settled the estimate is.
        alpha = s + PRIOR_ALPHA
        beta = (n - s) + PRIOR_BETA
        variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1))
        rates[stage] = {
            "advance_probability": round(posterior_mean, 4),
            "observed_attempts": n,
            "observed_advances": s,
            "observed_rate": round(s / n, 4) if n else None,
            "standard_error": round(math.sqrt(variance), 4),
            "evidence": "observed" if n >= 10 else "prior_dominated",
        }
    return rates


def probability_of_close(stage: str, rates: dict[str, dict]) -> float:
    """Chained probability of reaching close from the given stage."""
    index = stage_index(stage)
    if index is None:
        return 0.0
    if FUNNEL[index] == "closed":
        return 1.0
    probability = 1.0
    for step in FUNNEL[index:-1]:
        probability *= rates.get(step, {}).get("advance_probability", 0.0)
    return probability


def forecast(deals: list[dict], history: list[dict] | None = None) -> dict:
    """Produce a probability-weighted revenue forecast for the open pipeline.

    ``deals`` are open deals, each with ``stage``, ``projected_assignment_fee``,
    and ``updated_at``. ``history`` is the resolved-deal record used to fit
    conversion rates; when omitted, the prior alone is used and every rate is
    flagged ``prior_dominated``.
    """
    rates = estimate_conversion_rates(history or [])

    dwell_samples: dict[str, list[float]] = {stage: [] for stage in FUNNEL[:-1]}
    for deal in deals:
        stage = str(deal.get("stage") or "").strip().lower()
        days = _days_since(deal.get("updated_at"))
        if stage in dwell_samples and days is not None:
            dwell_samples[stage].append(days)

    typical_dwell = {
        stage: (_median(samples) if len(samples) >= 4 else DEFAULT_DWELL_DAYS.get(stage, 14.0))
        for stage, samples in dwell_samples.items()
    }

    entries: list[dict] = []
    total_expected = 0.0
    total_variance = 0.0
    total_nominal = 0.0
    stalled: list[dict] = []

    for deal in deals:
        stage = str(deal.get("stage") or "").strip().lower()
        if stage in TERMINAL_STAGES:
            continue
        fee = float(deal.get("projected_assignment_fee") or 0)
        probability = probability_of_close(stage, rates)
        expected = fee * probability

        total_nominal += fee
        total_expected += expected
        # Variance of fee * Bernoulli(p). Deals are treated as independent,
        # which understates variance if they share a market — noted in output.
        total_variance += (fee**2) * probability * (1 - probability)

        days_in_stage = _days_since(deal.get("updated_at"))
        threshold = max(MIN_STALL_DAYS, STALL_MULTIPLIER * typical_dwell.get(stage, 14.0))
        is_stalled = days_in_stage is not None and days_in_stage > threshold

        entry = {
            "deal_id": deal.get("id"),
            "stage": stage,
            "projected_assignment_fee": round(fee, 2),
            "probability_of_close": round(probability, 4),
            "expected_value": round(expected, 2),
            "days_in_stage": round(days_in_stage, 1) if days_in_stage is not None else None,
            "stalled": is_stalled,
        }
        entries.append(entry)
        if is_stalled:
            stalled.append(entry)

    standard_deviation = math.sqrt(total_variance)
    entries.sort(key=lambda item: item["expected_value"], reverse=True)

    return {
        "generated_at": _now().isoformat(),
        "open_deals": len(entries),
        "nominal_pipeline_value": round(total_nominal, 2),
        "expected_revenue": round(total_expected, 2),
        "revenue_interval": {
            "low": round(max(0.0, total_expected - 1.96 * standard_deviation), 2),
            "high": round(total_expected + 1.96 * standard_deviation, 2),
        },
        "overstatement_vs_nominal": round(total_nominal - total_expected, 2),
        "conversion_rates": rates,
        "typical_dwell_days": {k: round(v, 1) for k, v in typical_dwell.items()},
        "stage_distribution": _stage_distribution(entries),
        "bottlenecks": detect_bottlenecks(entries, typical_dwell, rates),
        "stalled_deals": sorted(stalled, key=lambda item: item["expected_value"], reverse=True),
        "deals": entries,
        "caveats": [
            "Deals are treated as independent; correlated market shocks would widen the interval.",
            "Days in stage is measured from the deal's last update, which is a lower bound on true dwell time.",
        ],
    }


def _stage_distribution(entries: list[dict]) -> dict[str, dict]:
    distribution: dict[str, dict] = {}
    for entry in entries:
        bucket = distribution.setdefault(
            entry["stage"], {"count": 0, "nominal_value": 0.0, "expected_value": 0.0}
        )
        bucket["count"] += 1
        bucket["nominal_value"] += entry["projected_assignment_fee"]
        bucket["expected_value"] += entry["expected_value"]
    for bucket in distribution.values():
        bucket["nominal_value"] = round(bucket["nominal_value"], 2)
        bucket["expected_value"] = round(bucket["expected_value"], 2)
    return distribution


def detect_bottlenecks(
    entries: list[dict], typical_dwell: dict[str, float], rates: dict[str, dict]
) -> list[dict]:
    """Rank stages by how much expected value is stuck in them.

    The severity metric is expected value held in the stage, scaled by how long
    deals sit there relative to the funnel and by how unlikely they are to
    advance. A stage holding a lot of value that moves quickly is not a
    bottleneck; one holding modest value that never advances is.
    """
    by_stage: dict[str, dict] = {}
    for entry in entries:
        bucket = by_stage.setdefault(entry["stage"], {"count": 0, "expected_value": 0.0, "stalled": 0})
        bucket["count"] += 1
        bucket["expected_value"] += entry["expected_value"]
        if entry["stalled"]:
            bucket["stalled"] += 1

    baseline_dwell = _median([v for v in typical_dwell.values() if v > 0]) or 14.0

    bottlenecks = []
    for stage, bucket in by_stage.items():
        dwell = typical_dwell.get(stage, baseline_dwell)
        advance = rates.get(stage, {}).get("advance_probability", 0.5)
        severity = bucket["expected_value"] * (dwell / baseline_dwell) * (1.0 - advance)
        bottlenecks.append(
            {
                "stage": stage,
                "deals": bucket["count"],
                "stalled_deals": bucket["stalled"],
                "expected_value_held": round(bucket["expected_value"], 2),
                "typical_dwell_days": round(dwell, 1),
                "advance_probability": round(advance, 4),
                "severity": round(severity, 2),
            }
        )

    return sorted(bottlenecks, key=lambda item: item["severity"], reverse=True)

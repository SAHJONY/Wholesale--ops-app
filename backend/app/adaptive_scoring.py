"""Outcome-calibrated lead scoring.

``services.lead_score`` weights motivation, equity, distress, and buyer demand
at a fixed 30/25/25/20 and returns a number on an arbitrary 0-100 scale. Those
weights were chosen up front and never move, the output is not a probability,
and nothing the desk learns from a closed deal ever feeds back into them —
despite ``fable5-plan.yaml`` ending its workflow with ``update_learning_records``.

This module closes that loop. It fits an L2-regularised logistic regression on
historical lead outcomes and returns a genuine probability of conversion, with:

* **Shrinkage to the prior.** With little history the model returns the legacy
  weighting, anchored to the observed base rate. As outcomes accumulate, the
  fitted model takes over smoothly. There is no cliff at which predictions
  suddenly change regime, and no point at which three data points get to
  overrule the prior.
* **Attribution.** Every score decomposes into per-feature log-odds
  contributions, so an operator can see *why* a lead ranks where it does.
* **Calibration reporting.** Brier score, log loss, and AUC are computed so the
  model's own reliability is visible rather than assumed.

Pure Python, no numeric dependencies, deterministic for a given training set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# How many observed outcomes it takes for the fitted model to carry half the
# weight against the prior. Deliberately conservative: wholesale conversion is
# a noisy, low-base-rate target and early samples are badly biased by whichever
# markets the desk happened to work first.
PRIOR_STRENGTH = 40.0

# Base rate used before any outcome is observed.
DEFAULT_BASE_RATE = 0.08

# Minimum observations, and minimum of each class, before a fit is attempted.
MIN_TRAINING_ROWS = 12
MIN_CLASS_COUNT = 3

L2_PENALTY = 1.0
MAX_ITERATIONS = 400
LEARNING_RATE = 0.5
CONVERGENCE_TOLERANCE = 1e-7

# Legacy weights, retained as the prior's ranking function.
PRIOR_WEIGHTS = {"motivation": 0.30, "equity": 0.25, "distress": 0.25, "buyer_demand": 0.20}
PRIOR_SCORE_SCALE = 12.5

FEATURE_NAMES = (
    "motivation",
    "equity",
    "distress",
    "buyer_demand",
    "timeline_urgency",
    "equity_spread",
    "lead_age_decay",
    "contactability",
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sigmoid(z: float) -> float:
    # Split by sign to keep exp() away from overflow at either extreme.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def _logit(p: float) -> float:
    p = _clamp(p, 1e-6, 1 - 1e-6)
    return math.log(p / (1 - p))


def extract_features(lead: dict) -> dict[str, float]:
    """Map a lead record onto the model's feature space.

    Every feature is scaled to roughly [0, 1] so that coefficients are
    comparable and standardisation stays well conditioned. Missing inputs
    resolve to a neutral value rather than zero, so absent data does not
    masquerade as a negative signal.
    """
    motivation = _clamp(float(lead.get("motivation_score") or 0) / 100.0)
    equity = _clamp(float(lead.get("equity_score") or 0) / 100.0)
    distress = _clamp(float(lead.get("distress_score") or 0) / 100.0)
    buyer_demand = _clamp(float(lead.get("buyer_demand_score") or 50) / 100.0)

    # Urgency decays with the seller's stated timeline: a 30-day seller is a
    # fundamentally different lead from a 12-month one.
    timeline_days = lead.get("timeline_days")
    if timeline_days is None:
        timeline_urgency = 0.5
    else:
        timeline_urgency = math.exp(-max(0.0, float(timeline_days)) / 90.0)

    # Spread between value and the seller's asking price, as a share of value.
    arv = float(lead.get("arv") or 0)
    asking = float(lead.get("asking_price") or 0)
    if arv > 0 and asking > 0:
        equity_spread = _clamp((arv - asking) / arv)
    else:
        equity_spread = 0.3

    age_days = lead.get("age_days")
    lead_age_decay = 0.5 if age_days is None else math.exp(-max(0.0, float(age_days)) / 45.0)

    contactability = 0.0
    if lead.get("phone"):
        contactability += 0.6
    if lead.get("email"):
        contactability += 0.4

    return {
        "motivation": motivation,
        "equity": equity,
        "distress": distress,
        "buyer_demand": buyer_demand,
        "timeline_urgency": timeline_urgency,
        "equity_spread": equity_spread,
        "lead_age_decay": lead_age_decay,
        "contactability": contactability,
    }


def prior_score(features: dict[str, float]) -> float:
    """The legacy 30/25/25/20 weighting, on its original 0-100 scale."""
    return 100.0 * sum(weight * features.get(name, 0.0) for name, weight in PRIOR_WEIGHTS.items())


def _prior_probability(features: dict[str, float], base_rate: float) -> float:
    """Legacy ranking, recentred so it reads as a calibrated probability.

    The legacy score preserved its ordering but implied a ~50% conversion rate
    at the qualification threshold, which is off by roughly an order of
    magnitude. Anchoring to the observed base rate keeps the ranking while
    making the number mean what it says.
    """
    return _sigmoid(_logit(base_rate) + (prior_score(features) - 50.0) / PRIOR_SCORE_SCALE)


@dataclass
class ScoringModel:
    """A fitted (or prior-only) conversion model."""

    coefficients: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    means: dict[str, float] = field(default_factory=dict)
    stddevs: dict[str, float] = field(default_factory=dict)
    base_rate: float = DEFAULT_BASE_RATE
    training_rows: int = 0
    positive_rows: int = 0
    fitted: bool = False
    blend_weight: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fitted": self.fitted,
            "training_rows": self.training_rows,
            "positive_rows": self.positive_rows,
            "base_rate": round(self.base_rate, 4),
            "blend_weight": round(self.blend_weight, 4),
            "coefficients": {k: round(v, 4) for k, v in self.coefficients.items()},
            "intercept": round(self.intercept, 4),
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "notes": list(self.notes),
        }


def _standardize(features: dict[str, float], model: ScoringModel) -> dict[str, float]:
    return {
        name: (features.get(name, 0.0) - model.means.get(name, 0.0))
        / (model.stddevs.get(name) or 1.0)
        for name in FEATURE_NAMES
    }


def fit(training_rows: list[tuple[dict, int]]) -> ScoringModel:
    """Fit a conversion model from ``(lead_record, outcome)`` pairs.

    ``outcome`` is 1 when the lead converted to a closed deal and 0 when it
    died. Leads still in flight must be excluded by the caller — including them
    as zeros would train the model to predict "not closed yet".
    """
    model = ScoringModel()
    rows = [(extract_features(lead), int(bool(label))) for lead, label in training_rows]
    model.training_rows = len(rows)
    model.positive_rows = sum(label for _, label in rows)

    if rows:
        model.base_rate = _clamp(model.positive_rows / len(rows), 0.005, 0.995)

    negatives = len(rows) - model.positive_rows
    if len(rows) < MIN_TRAINING_ROWS:
        model.notes.append(
            f"Only {len(rows)} outcome(s) recorded; scoring uses the prior weighting until "
            f"{MIN_TRAINING_ROWS} are available."
        )
        return model
    if model.positive_rows < MIN_CLASS_COUNT or negatives < MIN_CLASS_COUNT:
        model.notes.append(
            f"Outcomes are too one-sided to fit ({model.positive_rows} converted, "
            f"{negatives} did not); scoring uses the prior weighting."
        )
        return model

    # Standardise. A zero-variance feature is carried at std 1 so its
    # standardised value is a constant 0 and it simply drops out of the fit.
    n = len(rows)
    for name in FEATURE_NAMES:
        column = [features[name] for features, _ in rows]
        mean = sum(column) / n
        variance = sum((value - mean) ** 2 for value in column) / n
        stddev = math.sqrt(variance)
        model.means[name] = mean
        model.stddevs[name] = stddev if stddev > 1e-9 else 1.0
        if stddev <= 1e-9:
            model.notes.append(f"Feature {name!r} has no variance in the training set and was ignored.")

    design = [([( features[name] - model.means[name]) / model.stddevs[name] for name in FEATURE_NAMES], label)
              for features, label in rows]

    weights = [0.0] * len(FEATURE_NAMES)
    intercept = _logit(model.base_rate)
    previous_loss = float("inf")

    for _ in range(MAX_ITERATIONS):
        gradient = [0.0] * len(FEATURE_NAMES)
        intercept_gradient = 0.0
        loss = 0.0

        for vector, label in design:
            z = intercept + sum(w * x for w, x in zip(weights, vector))
            prediction = _sigmoid(z)
            error = prediction - label
            intercept_gradient += error
            for index, x in enumerate(vector):
                gradient[index] += error * x
            # Clamped log loss; the clamp only bites on saturated predictions.
            p = _clamp(prediction, 1e-9, 1 - 1e-9)
            loss -= label * math.log(p) + (1 - label) * math.log(1 - p)

        loss = loss / n + 0.5 * L2_PENALTY * sum(w * w for w in weights) / n

        for index in range(len(weights)):
            gradient[index] = gradient[index] / n + L2_PENALTY * weights[index] / n
            weights[index] -= LEARNING_RATE * gradient[index]
        intercept -= LEARNING_RATE * intercept_gradient / n

        if abs(previous_loss - loss) < CONVERGENCE_TOLERANCE:
            break
        previous_loss = loss

    model.coefficients = dict(zip(FEATURE_NAMES, weights))
    model.intercept = intercept
    model.fitted = True
    model.blend_weight = n / (n + PRIOR_STRENGTH)

    predictions = [
        (_sigmoid(intercept + sum(w * x for w, x in zip(weights, vector))), label)
        for vector, label in design
    ]
    model.metrics = _calibration_metrics(predictions)
    return model


def _calibration_metrics(predictions: list[tuple[float, int]]) -> dict[str, float]:
    """Brier score, log loss, and AUC over in-sample predictions.

    These are in-sample and therefore optimistic — they answer "did the fit
    converge onto something sensible", not "how will this generalise". Reported
    rather than hidden so nobody mistakes them for held-out performance.
    """
    if not predictions:
        return {}
    n = len(predictions)
    brier = sum((p - label) ** 2 for p, label in predictions) / n
    log_loss = -sum(
        label * math.log(_clamp(p, 1e-9, 1 - 1e-9)) + (1 - label) * math.log(_clamp(1 - p, 1e-9, 1 - 1e-9))
        for p, label in predictions
    ) / n

    positives = [p for p, label in predictions if label == 1]
    negatives = [p for p, label in predictions if label == 0]
    if positives and negatives:
        # Rank-based AUC: the probability a random positive outranks a random
        # negative, with ties counted as half.
        wins = sum(
            1.0 if pos > neg else 0.5 if pos == neg else 0.0
            for pos in positives
            for neg in negatives
        )
        auc = wins / (len(positives) * len(negatives))
    else:
        auc = 0.5

    return {"brier_score": brier, "log_loss": log_loss, "auc": auc, "in_sample": 1.0}


def score(lead: dict, model: ScoringModel | None = None) -> dict:
    """Score one lead, returning a probability and its attribution."""
    model = model or ScoringModel()
    features = extract_features(lead)
    prior_probability = _prior_probability(features, model.base_rate)

    if not model.fitted:
        probability = prior_probability
        attribution = _prior_attribution(features)
        blend = 0.0
    else:
        standardized = _standardize(features, model)
        contributions = {
            name: model.coefficients.get(name, 0.0) * standardized[name] for name in FEATURE_NAMES
        }
        fitted_probability = _sigmoid(model.intercept + sum(contributions.values()))
        blend = model.blend_weight
        # Blend in log-odds space so the result stays a well-formed probability
        # and neither component can drag the other past a bound.
        probability = _sigmoid(
            blend * _logit(fitted_probability) + (1 - blend) * _logit(prior_probability)
        )
        attribution = _rank_attribution(contributions)

    return {
        "probability": round(probability, 4),
        "score": round(probability * 100, 2),
        "prior_probability": round(prior_probability, 4),
        "legacy_score": round(prior_score(features), 2),
        "blend_weight": round(blend, 4),
        "model_fitted": model.fitted,
        "features": {name: round(value, 4) for name, value in features.items()},
        "attribution": attribution,
        "band": _band(probability, model.base_rate),
    }


def _rank_attribution(contributions: dict[str, float]) -> list[dict]:
    total = sum(abs(value) for value in contributions.values()) or 1.0
    ordered = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
    return [
        {
            "feature": name,
            "log_odds": round(value, 4),
            "share": round(abs(value) / total * 100, 1),
            "direction": "increases" if value > 0 else "decreases" if value < 0 else "neutral",
        }
        for name, value in ordered
    ]


def _prior_attribution(features: dict[str, float]) -> list[dict]:
    contributions = {name: weight * features.get(name, 0.0) for name, weight in PRIOR_WEIGHTS.items()}
    total = sum(contributions.values()) or 1.0
    ordered = sorted(contributions.items(), key=lambda item: item[1], reverse=True)
    return [
        {
            "feature": name,
            "log_odds": None,
            "share": round(value / total * 100, 1),
            "direction": "increases" if value > 0 else "neutral",
        }
        for name, value in ordered
    ]


def _band(probability: float, base_rate: float) -> str:
    """Bucket a lead relative to the population it came from.

    Bands are expressed as multiples of the base rate rather than absolute
    thresholds: in a low-conversion market a 20% lead is exceptional, and a
    fixed cutoff would call it mediocre.
    """
    ratio = probability / max(base_rate, 1e-6)
    if ratio >= 2.5:
        return "priority"
    if ratio >= 1.5:
        return "qualified"
    if ratio >= 0.75:
        return "nurture"
    return "deprioritize"


def rank(leads: list[dict], model: ScoringModel | None = None) -> list[dict]:
    """Score and rank a set of leads, highest conversion probability first."""
    scored = []
    for lead in leads:
        result = score(lead, model)
        result["lead_id"] = lead.get("id")
        scored.append(result)
    return sorted(scored, key=lambda item: item["probability"], reverse=True)

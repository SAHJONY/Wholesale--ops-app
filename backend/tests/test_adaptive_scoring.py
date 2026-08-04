import random

import pytest

from app import adaptive_scoring


def lead(motivation=50, equity=50, distress=50, timeline=90, **overrides):
    record = {
        "motivation_score": motivation,
        "equity_score": equity,
        "distress_score": distress,
        "timeline_days": timeline,
        "phone": "555-0100",
    }
    record.update(overrides)
    return record


def synthetic_training_set(count=200, seed=11):
    """Leads whose true conversion depends on motivation, equity, and urgency.

    Distress and buyer demand are deliberately noise, so a correctly fitted
    model should learn to discount them — which the fixed 25% distress weight
    in the legacy scorer cannot do.
    """
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        motivation = rng.uniform(0, 100)
        equity = rng.uniform(0, 100)
        distress = rng.uniform(0, 100)
        timeline = rng.choice([15, 30, 60, 180, 365])
        record = lead(motivation, equity, distress, timeline)
        z = -3.2 + 2.5 * (motivation / 100) + 1.8 * (equity / 100) + 1.2 * (2.718 ** (-timeline / 90))
        probability = 1 / (1 + 2.718 ** (-z))
        rows.append((record, 1 if rng.random() < probability else 0))
    return rows


class TestFeatureExtraction:
    def test_missing_inputs_resolve_to_neutral_not_zero(self):
        features = adaptive_scoring.extract_features({})
        assert features["timeline_urgency"] == 0.5
        assert features["lead_age_decay"] == 0.5
        assert features["equity_spread"] == 0.3

    def test_shorter_timeline_is_more_urgent(self):
        soon = adaptive_scoring.extract_features(lead(timeline=15))["timeline_urgency"]
        later = adaptive_scoring.extract_features(lead(timeline=365))["timeline_urgency"]
        assert soon > later

    def test_features_stay_within_the_unit_range(self):
        features = adaptive_scoring.extract_features(
            lead(motivation=1e6, equity=-500, arv=100, asking_price=1e9, age_days=-5)
        )
        assert all(0.0 <= value <= 1.0 for value in features.values())

    def test_contactability_reflects_available_channels(self):
        neither = adaptive_scoring.extract_features({"motivation_score": 10})["contactability"]
        both = adaptive_scoring.extract_features(
            {"phone": "555", "email": "a@b.co"}
        )["contactability"]
        assert neither == 0.0
        assert both == 1.0


class TestFitting:
    def test_too_few_outcomes_falls_back_to_the_prior(self):
        model = adaptive_scoring.fit([(lead(), 1), (lead(), 0)])
        assert model.fitted is False
        assert any("prior weighting" in note for note in model.notes)

    def test_one_sided_outcomes_cannot_be_fitted(self):
        model = adaptive_scoring.fit([(lead(), 1)] * 30)
        assert model.fitted is False
        assert any("one-sided" in note for note in model.notes)

    def test_fits_once_enough_outcomes_exist(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        assert model.fitted is True
        assert model.training_rows == 200
        assert 0 < model.blend_weight < 1

    def test_learns_the_true_drivers_and_discounts_the_noise(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        assert model.coefficients["motivation"] > 0.2
        assert model.coefficients["equity"] > 0.2
        # Distress carries a fixed 25% in the legacy scorer but contributes
        # nothing to conversion in this population.
        assert abs(model.coefficients["distress"]) < model.coefficients["motivation"] / 2

    def test_reports_its_own_calibration(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        assert 0.0 <= model.metrics["brier_score"] <= 1.0
        assert model.metrics["auc"] > 0.6
        assert model.metrics["in_sample"] == 1.0

    def test_base_rate_reflects_observed_conversions(self):
        rows = [(lead(), 1)] * 20 + [(lead(), 0)] * 80
        model = adaptive_scoring.fit(rows)
        assert model.base_rate == 0.2


class TestScoring:
    def test_untrained_scoring_uses_the_prior_and_says_so(self):
        result = adaptive_scoring.score(lead(motivation=90))
        assert result["model_fitted"] is False
        assert result["blend_weight"] == 0.0
        assert result["probability"] == result["prior_probability"]

    def test_probability_is_always_a_valid_probability(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        for record in (lead(0, 0, 0, 3650), lead(100, 100, 100, 1), lead()):
            assert 0.0 <= adaptive_scoring.score(record, model)["probability"] <= 1.0

    def test_better_leads_score_higher(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        hot = adaptive_scoring.score(lead(95, 90, 70, 20), model)["probability"]
        cold = adaptive_scoring.score(lead(10, 15, 5, 365), model)["probability"]
        assert hot > cold

    def test_attribution_explains_the_whole_score(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        attribution = adaptive_scoring.score(lead(95, 90, 70, 20), model)["attribution"]
        assert sum(row["share"] for row in attribution) == pytest.approx(100.0, abs=0.5)
        assert attribution == sorted(attribution, key=lambda row: row["share"], reverse=True)

    def test_bands_are_relative_to_the_population_base_rate(self):
        # The same absolute probability means different things in a 2% market
        # and a 40% one, so banding must be relative.
        low_base = adaptive_scoring.ScoringModel(base_rate=0.02)
        high_base = adaptive_scoring.ScoringModel(base_rate=0.40)
        assert adaptive_scoring._band(0.10, low_base.base_rate) == "priority"
        assert adaptive_scoring._band(0.10, high_base.base_rate) == "deprioritize"

    def test_legacy_score_is_preserved_for_comparison(self):
        result = adaptive_scoring.score(lead(80, 60, 40))
        expected = 100 * (0.30 * 0.8 + 0.25 * 0.6 + 0.25 * 0.4 + 0.20 * 0.5)
        assert result["legacy_score"] == pytest.approx(expected, abs=0.01)


class TestRanking:
    def test_ranks_highest_probability_first(self):
        model = adaptive_scoring.fit(synthetic_training_set())
        records = [
            dict(lead(10, 10, 10, 365), id=1),
            dict(lead(95, 95, 50, 15), id=2),
            dict(lead(50, 50, 50, 90), id=3),
        ]
        ranked = adaptive_scoring.rank(records, model)
        assert [row["lead_id"] for row in ranked] == [2, 3, 1]

    def test_ranking_an_empty_set_is_not_an_error(self):
        assert adaptive_scoring.rank([]) == []

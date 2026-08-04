import pytest

from app import buyer_intelligence


def buyer(buyer_id=1, name="Apex", **overrides):
    record = {
        "id": buyer_id,
        "name": name,
        "zip_codes": ["32501"],
        "asset_types": ["single_family"],
        "min_price": 50_000,
        "max_price": 150_000,
        "max_rehab": 80_000,
        "closing_days": 14,
        "proof_of_funds_verified": True,
        "response_rate": 60,
        "reliability_score": 80,
        "days_since_last_contact": 10,
    }
    record.update(overrides)
    return record


def prop(**overrides):
    record = {
        "id": 10,
        "zip_code": "32501",
        "property_type": "single_family",
        "mao": 100_000,
        "repairs": 40_000,
    }
    record.update(overrides)
    return record


class TestBuyBoxFit:
    def test_perfect_match_scores_near_one(self):
        fit, _ = buyer_intelligence.buy_box_fit(buyer(), prop())
        assert fit > 0.9

    def test_wrong_zip_loses_the_location_component(self):
        fit, components = buyer_intelligence.buy_box_fit(buyer(), prop(zip_code="99999"))
        assert components["location"] == 0.0
        assert fit < 0.75

    def test_excess_rehab_partially_credits_rather_than_zeroing(self):
        _, components = buyer_intelligence.buy_box_fit(
            buyer(max_rehab=40_000), prop(repairs=80_000)
        )
        assert 0.0 < components["rehab"] < 1.0

    def test_price_fit_peaks_mid_band(self):
        middle = buyer_intelligence._price_fit(100_000, 50_000, 150_000)
        edge = buyer_intelligence._price_fit(149_000, 50_000, 150_000)
        outside = buyer_intelligence._price_fit(400_000, 50_000, 150_000)
        assert middle > edge > outside

    def test_price_outside_the_band_decays_but_is_not_zero(self):
        assert 0.0 < buyer_intelligence._price_fit(160_000, 50_000, 150_000) < 0.5


class TestEngagementDecay:
    def test_recent_contact_beats_stale_contact(self):
        fresh = buyer_intelligence.engagement(buyer(days_since_last_contact=5))
        stale = buyer_intelligence.engagement(buyer(days_since_last_contact=400))
        assert fresh > stale * 3

    def test_identical_buyers_differ_only_by_recency(self):
        # This is the case the legacy flat response_rate could not distinguish.
        fresh = buyer_intelligence.response_probability(
            buyer(days_since_last_contact=5), prop()
        )["response_probability"]
        stale = buyer_intelligence.response_probability(
            buyer(days_since_last_contact=500), prop()
        )["response_probability"]
        assert fresh > stale

    def test_unknown_contact_history_uses_a_documented_default(self):
        record = buyer()
        record.pop("days_since_last_contact")
        assert buyer_intelligence.engagement(record) > 0


class TestResponseProbability:
    def test_returns_a_probability_with_drivers(self):
        result = buyer_intelligence.response_probability(buyer(), prop())
        assert 0.0 <= result["response_probability"] <= 1.0
        assert result["drivers"]
        assert sum(row["share"] for row in result["drivers"]) == pytest.approx(100.0, abs=0.5)

    def test_unreliable_buyers_are_expected_to_close_later(self):
        reliable = buyer_intelligence.response_probability(
            buyer(reliability_score=100), prop()
        )["expected_days_to_close"]
        flaky = buyer_intelligence.response_probability(
            buyer(reliability_score=0), prop()
        )["expected_days_to_close"]
        assert flaky > reliable

    def test_reasons_flag_a_buyer_with_no_track_record(self):
        result = buyer_intelligence.response_probability(
            buyer(response_rate=0, days_since_last_contact=900), prop()
        )
        assert any("unproven" in reason for reason in result["reasons"])

    def test_ranking_orders_by_probability(self):
        buyers = [
            buyer(1, "Strong"),
            buyer(2, "Weak", zip_codes=["99999"], response_rate=5, reliability_score=10),
        ]
        ranked = buyer_intelligence.rank_buyers(prop(), buyers)
        assert [row["buyer_name"] for row in ranked] == ["Strong", "Weak"]

    def test_minimum_probability_filters_the_list(self):
        buyers = [buyer(1), buyer(2, zip_codes=["99999"], response_rate=0, reliability_score=0)]
        assert len(buyer_intelligence.rank_buyers(prop(), buyers, minimum_probability=0.9)) < 2


class TestPortfolioAssignment:
    def deals(self, fees):
        return [
            {"id": index + 1, "projected_assignment_fee": fee, "property": prop()}
            for index, fee in enumerate(fees)
        ]

    def test_respects_buyer_capacity(self):
        buyers = [buyer(1), buyer(2)]
        plan = buyer_intelligence.optimize_assignments(
            self.deals([20_000, 18_000, 15_000, 12_000]), buyers, buyer_capacity=1
        )
        assert all(load <= 1 for load in plan["buyer_utilization"].values())
        assert len(plan["assignments"]) == 2
        assert len(plan["unmatched_deals"]) == 2

    def test_best_buyer_goes_to_the_highest_value_deal(self):
        buyers = [
            buyer(1, "Strong"),
            buyer(2, "Weak", response_rate=10, reliability_score=20, days_since_last_contact=300),
        ]
        plan = buyer_intelligence.optimize_assignments(
            self.deals([50_000, 5_000]), buyers, buyer_capacity=1
        )
        by_deal = {row["deal_id"]: row["buyer_name"] for row in plan["assignments"]}
        assert by_deal[1] == "Strong"
        assert by_deal[2] == "Weak"

    def test_a_deal_never_gets_the_same_buyer_twice(self):
        plan = buyer_intelligence.optimize_assignments(
            self.deals([20_000]), [buyer(1), buyer(2)], buyer_capacity=5, offers_per_deal=2
        )
        buyers_for_deal = [row["buyer_id"] for row in plan["assignments"] if row["deal_id"] == 1]
        assert len(buyers_for_deal) == len(set(buyers_for_deal))

    def test_capacity_constrained_revenue_never_exceeds_the_unconstrained_bound(self):
        plan = buyer_intelligence.optimize_assignments(
            self.deals([20_000, 18_000, 15_000]), [buyer(1), buyer(2)], buyer_capacity=1
        )
        assert plan["expected_revenue"] <= plan["unconstrained_expected_revenue"] + 1e-6

    def test_raising_capacity_never_lowers_expected_revenue(self):
        deals = self.deals([20_000, 18_000, 15_000])
        buyers = [buyer(1), buyer(2)]
        tight = buyer_intelligence.optimize_assignments(deals, buyers, buyer_capacity=1)
        loose = buyer_intelligence.optimize_assignments(deals, buyers, buyer_capacity=3)
        assert loose["expected_revenue"] >= tight["expected_revenue"]

    def test_buyers_below_the_probability_floor_are_never_assigned(self):
        plan = buyer_intelligence.optimize_assignments(
            self.deals([20_000]),
            [buyer(1, zip_codes=["99999"], response_rate=0, reliability_score=0)],
            minimum_probability=0.99,
        )
        assert plan["assignments"] == []
        assert plan["unmatched_deals"] == [1]

    def test_invalid_parameters_are_rejected(self):
        with pytest.raises(ValueError):
            buyer_intelligence.optimize_assignments(self.deals([1]), [buyer()], buyer_capacity=0)
        with pytest.raises(ValueError):
            buyer_intelligence.optimize_assignments(self.deals([1]), [buyer()], offers_per_deal=0)

    def test_empty_inputs_produce_an_empty_plan(self):
        assert buyer_intelligence.optimize_assignments([], [])["assignments"] == []

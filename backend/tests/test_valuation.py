from datetime import date

import pytest

from app.valuation import (
    Comparable,
    SubjectProperty,
    ValuationError,
    estimate_arv,
    estimate_repairs,
    simulate_deal,
    underwrite,
)

AS_OF = date(2026, 7, 27)


def subject(**overrides):
    defaults = dict(
        sqft=1500, bedrooms=3, bathrooms=2.0, year_built=1985, condition="moderate", distress_signals=()
    )
    defaults.update(overrides)
    return SubjectProperty(**defaults)


def comp(address="1 A St", price=250_000.0, sqft=1500, sold=date(2026, 5, 1), **overrides):
    defaults = dict(
        bedrooms=3, bathrooms=2.0, year_built=1985, distance_miles=0.4, condition="good"
    )
    defaults.update(overrides)
    return Comparable(address=address, sale_price=price, sale_date=sold, sqft=sqft, **defaults)


def comp_set(count=5):
    return [
        comp(f"{index} Main St", price=250_000 + index * 3_000, sqft=1480 + index * 20)
        for index in range(count)
    ]


class TestSalesComparisonGrid:
    def test_larger_subject_adjusts_comp_upward(self):
        result = estimate_arv(subject(sqft=2000), [comp(sqft=1500)], as_of=AS_OF)
        row = result.comparables[0]
        assert row.adjustments["size"] > 0
        assert row.adjusted_price > row.sale_price

    def test_smaller_subject_adjusts_comp_downward(self):
        result = estimate_arv(subject(sqft=1200), [comp(sqft=1500)], as_of=AS_OF)
        assert result.comparables[0].adjustments["size"] < 0

    def test_older_sale_is_adjusted_forward_to_current_market(self):
        recent = estimate_arv(subject(), [comp(sold=date(2026, 7, 1))], as_of=AS_OF)
        stale = estimate_arv(subject(), [comp(sold=date(2024, 7, 1))], as_of=AS_OF)
        assert stale.comparables[0].adjustments["market_time"] > recent.comparables[0].adjustments["market_time"]

    def test_arv_basis_adjusts_poor_condition_comp_upward(self):
        result = estimate_arv(subject(), [comp(condition="gut")], as_of=AS_OF, basis="arv")
        assert result.comparables[0].adjustments["condition"] > 0

    def test_nearby_recent_comp_outweighs_distant_stale_one(self):
        near = comp("near", distance_miles=0.1, sold=date(2026, 7, 1))
        far = comp("far", distance_miles=6.0, sold=date(2023, 1, 1))
        result = estimate_arv(subject(), [near, far], as_of=AS_OF)
        weights = {row.address: row.weight for row in result.comparables}
        assert weights["near"] > weights["far"] * 10


class TestOutliersAndConfidence:
    def test_outlier_comp_is_rejected(self):
        comps = comp_set(6) + [comp("wild", price=900_000.0)]
        result = estimate_arv(subject(), comps, as_of=AS_OF)
        rejected = [row for row in result.comparables if row.excluded]
        assert any(row.address == "wild" for row in rejected)
        assert result.arv < 400_000

    def test_confidence_interval_brackets_the_estimate(self):
        result = estimate_arv(subject(), comp_set(6), as_of=AS_OF)
        assert result.low < result.arv < result.high

    def test_disagreeing_comps_lower_confidence_and_widen_interval(self):
        tight = estimate_arv(subject(), comp_set(6), as_of=AS_OF)
        spread = [
            comp(f"{index} Wide St", price=180_000 + index * 30_000, sqft=1500) for index in range(6)
        ]
        loose = estimate_arv(subject(), spread, as_of=AS_OF)
        assert loose.confidence < tight.confidence
        assert (loose.high - loose.low) > (tight.high - tight.low)

    def test_thin_comp_set_is_flagged(self):
        result = estimate_arv(subject(), [comp()], as_of=AS_OF)
        assert any("effective comparable" in warning for warning in result.warnings)

    def test_no_comparables_is_an_error_not_a_guess(self):
        with pytest.raises(ValuationError):
            estimate_arv(subject(), [], as_of=AS_OF)

    def test_zero_square_footage_is_rejected(self):
        with pytest.raises(ValuationError):
            estimate_arv(subject(sqft=0), comp_set(), as_of=AS_OF)

    def test_wholly_mismatched_comps_refuse_to_produce_an_estimate(self):
        # A subject ten times the size of every comp requires adjustments far
        # beyond the acceptable limit; the engine must decline rather than
        # extrapolate.
        with pytest.raises(ValuationError):
            estimate_arv(subject(sqft=15_000), comp_set(4), as_of=AS_OF)


class TestRepairModel:
    def test_worse_condition_costs_more(self):
        light = estimate_repairs(subject(condition="cosmetic"))["total"]
        heavy = estimate_repairs(subject(condition="gut"))["total"]
        assert heavy > light

    def test_distress_signals_add_line_items(self):
        clean = estimate_repairs(subject())["total"]
        damaged = estimate_repairs(subject(distress_signals=("roof_damage", "foundation_issue")))
        assert damaged["total"] > clean
        assert set(damaged["line_items"]) == {"roof_damage", "foundation_issue"}

    def test_repeated_signals_are_counted_once(self):
        once = estimate_repairs(subject(distress_signals=("roof_damage",)))["total"]
        twice = estimate_repairs(subject(distress_signals=("roof_damage", "roof_damage")))["total"]
        assert once == twice

    def test_repairs_are_capped_against_arv(self):
        result = estimate_repairs(subject(sqft=4000, condition="gut"), arv=100_000)
        assert result["capped_at_arv_share"] is True
        assert result["total"] <= 100_000 * 0.75

    def test_unknown_signals_are_ignored_rather_than_guessed(self):
        result = estimate_repairs(subject(distress_signals=("alien_invasion",)))
        assert result["line_items"] == {}


class TestSimulation:
    def test_higher_contract_price_lowers_success_probability(self):
        cheap = simulate_deal(arv=250_000, repairs=40_000, contract_price=90_000)
        pricey = simulate_deal(arv=250_000, repairs=40_000, contract_price=130_000)
        assert cheap.probability_of_target > pricey.probability_of_target

    def test_recommended_offer_meets_the_confidence_target(self):
        first = simulate_deal(
            arv=250_000, repairs=40_000, contract_price=0, confidence_target=0.8
        )
        priced = simulate_deal(
            arv=250_000,
            repairs=40_000,
            contract_price=first.recommended_max_offer,
            confidence_target=0.8,
        )
        assert priced.probability_of_target == pytest.approx(0.8, abs=0.03)

    def test_wider_valuation_uncertainty_lowers_the_recommended_offer(self):
        certain = simulate_deal(
            arv=250_000, arv_low=245_000, arv_high=255_000, repairs=40_000, contract_price=0
        )
        uncertain = simulate_deal(
            arv=250_000, arv_low=190_000, arv_high=310_000, repairs=40_000, contract_price=0
        )
        assert uncertain.recommended_max_offer < certain.recommended_max_offer

    def test_results_are_reproducible_for_a_given_seed(self):
        kwargs = dict(arv=250_000, repairs=40_000, contract_price=100_000, seed=99)
        assert simulate_deal(**kwargs).as_dict() == simulate_deal(**kwargs).as_dict()

    def test_percentiles_are_monotonic(self):
        percentiles = simulate_deal(arv=250_000, repairs=40_000, contract_price=100_000).percentiles
        ordered = [percentiles[key] for key in ("p10", "p25", "p50", "p75", "p90")]
        assert ordered == sorted(ordered)

    def test_invalid_confidence_target_is_rejected(self):
        with pytest.raises(ValuationError):
            simulate_deal(arv=250_000, repairs=40_000, contract_price=0, confidence_target=1.0)


class TestUnderwriteChain:
    def test_produces_a_complete_decision_record(self):
        result = underwrite(subject(distress_signals=("roof_damage",)), comp_set(6))
        assert result["valuation"]["arv"] > 0
        assert result["repairs"]["total"] > 0
        assert result["recommended_max_offer"] >= 0
        assert result["decision_quality"]["verdict"] in {
            "proceed",
            "marginal",
            "reject",
            "insufficient_data",
        }

    def test_an_overpriced_contract_is_rejected(self):
        result = underwrite(subject(), comp_set(6), contract_price=400_000)
        assert result["decision_quality"]["verdict"] == "reject"
        assert result["simulation"]["probability_of_target"] < 0.5

    def test_repairs_override_is_honoured(self):
        result = underwrite(subject(), comp_set(6), repairs_override=1_000)
        assert result["repairs_used"] == 1_000

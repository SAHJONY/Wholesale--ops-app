from datetime import datetime, timedelta, timezone

from app import pipeline_forecast

NOW = datetime.now(timezone.utc)


def deal(deal_id=1, stage="qualified", fee=20_000, days_idle=1):
    return {
        "id": deal_id,
        "stage": stage,
        "projected_assignment_fee": fee,
        "updated_at": NOW - timedelta(days=days_idle),
    }


def history(closed=10, died_at="qualified", died=40):
    return [{"furthest_stage": "closing", "outcome": "closed"}] * closed + [
        {"furthest_stage": died_at, "outcome": "dead"}
    ] * died


class TestConversionRates:
    def test_thin_evidence_is_smoothed_away_from_zero_and_one(self):
        rates = pipeline_forecast.estimate_conversion_rates(
            [{"furthest_stage": "closing", "outcome": "closed"}]
        )
        for stage in rates.values():
            assert 0.0 < stage["advance_probability"] < 1.0

    def test_no_history_still_yields_usable_priors(self):
        rates = pipeline_forecast.estimate_conversion_rates([])
        assert all(row["evidence"] == "prior_dominated" for row in rates.values())
        assert all(0.0 < row["advance_probability"] < 1.0 for row in rates.values())

    def test_sufficient_history_is_marked_observed(self):
        rates = pipeline_forecast.estimate_conversion_rates(history())
        assert rates["nurture"]["evidence"] == "observed"
        assert rates["nurture"]["observed_attempts"] == 50

    def test_a_stage_where_deals_die_shows_a_lower_advance_rate(self):
        rates = pipeline_forecast.estimate_conversion_rates(history(closed=10, died_at="qualified", died=90))
        assert rates["qualified"]["advance_probability"] < rates["nurture"]["advance_probability"]

    def test_unknown_stages_are_skipped_not_coerced(self):
        rates = pipeline_forecast.estimate_conversion_rates(
            [{"furthest_stage": "invented_stage", "outcome": "dead"}]
        )
        assert all(row["observed_attempts"] == 0 for row in rates.values())


class TestProbabilityOfClose:
    def test_later_stages_are_likelier_to_close(self):
        rates = pipeline_forecast.estimate_conversion_rates(history())
        early = pipeline_forecast.probability_of_close("nurture", rates)
        late = pipeline_forecast.probability_of_close("closing", rates)
        assert late > early

    def test_a_closed_deal_is_certain(self):
        rates = pipeline_forecast.estimate_conversion_rates(history())
        assert pipeline_forecast.probability_of_close("closed", rates) == 1.0

    def test_an_unknown_stage_contributes_nothing(self):
        rates = pipeline_forecast.estimate_conversion_rates(history())
        assert pipeline_forecast.probability_of_close("not_a_stage", rates) == 0.0


class TestForecast:
    def test_expected_revenue_is_below_the_nominal_sum(self):
        result = pipeline_forecast.forecast(
            [deal(1, "nurture"), deal(2, "qualified"), deal(3, "contracted")], history()
        )
        assert result["expected_revenue"] < result["nominal_pipeline_value"]
        assert result["overstatement_vs_nominal"] > 0

    def test_interval_brackets_the_point_estimate(self):
        result = pipeline_forecast.forecast([deal(1), deal(2, "closing")], history())
        assert result["revenue_interval"]["low"] <= result["expected_revenue"]
        assert result["expected_revenue"] <= result["revenue_interval"]["high"]

    def test_terminal_deals_are_excluded_from_the_open_pipeline(self):
        result = pipeline_forecast.forecast(
            [deal(1, "closed"), deal(2, "dead"), deal(3, "qualified")], history()
        )
        assert result["open_deals"] == 1

    def test_idle_deals_are_flagged_as_stalled(self):
        result = pipeline_forecast.forecast(
            [deal(1, "closing", days_idle=120), deal(2, "closing", days_idle=1)], history()
        )
        assert [row["deal_id"] for row in result["stalled_deals"]] == [1]

    def test_deals_are_ordered_by_expected_value(self):
        result = pipeline_forecast.forecast(
            [deal(1, "nurture", fee=5_000), deal(2, "closing", fee=50_000)], history()
        )
        values = [row["expected_value"] for row in result["deals"]]
        assert values == sorted(values, reverse=True)

    def test_empty_pipeline_forecasts_zero_without_error(self):
        result = pipeline_forecast.forecast([], [])
        assert result["expected_revenue"] == 0.0
        assert result["open_deals"] == 0

    def test_caveats_are_always_stated(self):
        assert pipeline_forecast.forecast([deal()], history())["caveats"]


class TestBottlenecks:
    def test_ranks_the_stage_holding_the_most_stuck_value_first(self):
        result = pipeline_forecast.forecast(
            [
                deal(1, "qualified", fee=40_000, days_idle=200),
                deal(2, "qualified", fee=40_000, days_idle=200),
                deal(3, "contracted", fee=5_000, days_idle=1),
            ],
            history(closed=5, died_at="qualified", died=95),
        )
        assert result["bottlenecks"][0]["stage"] == "qualified"
        assert result["bottlenecks"][0]["stalled_deals"] == 2

    def test_severity_is_ordered_descending(self):
        result = pipeline_forecast.forecast(
            [deal(1, "nurture"), deal(2, "qualified"), deal(3, "closing")], history()
        )
        severities = [row["severity"] for row in result["bottlenecks"]]
        assert severities == sorted(severities, reverse=True)

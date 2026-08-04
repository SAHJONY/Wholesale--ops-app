"""Tests for the free public market-data connectors.

These use ``httpx.MockTransport`` with fixtures shaped like the real Census and
FHFA responses, so the full fetch path is exercised without touching the
network. Response shapes here mirror the published formats: Census returns an
array-of-arrays with a header row and negative "jam value" sentinels for
suppressed estimates; FHFA publishes CSV with named columns.
"""

import httpx
import pytest

from app import market_data as md

# --- Fixtures -------------------------------------------------------------

ACS_HEADER = [
    "NAME",
    "B25077_001E",
    "B25064_001E",
    "B25003_001E",
    "B25003_002E",
    "B25002_001E",
    "B25002_003E",
    "B25035_001E",
    "B19013_001E",
    "B25077_001M",
    "B25064_001M",
    "zip code tabulation area",
]
ACS_ROW = [
    "ZCTA5 32501", "145600", "1024", "4210", "1902",
    "5130", "920", "1962", "41250", "12800", "88", "32501",
]
# Census publishes negative sentinels when an estimate cannot be released.
ACS_SUPPRESSED_ROW = [
    "ZCTA5 99999", "-666666666", "-666666666", "12", "5",
    "30", "18", "-666666666", "-666666666", "-555555555", "-555555555", "99999",
]

FHFA_ZIP5_CSV = (
    "Five-Digit ZIP Code,Year,Annual Change (%),HPI,HPI with 1990 base,HPI with 2000 base\n"
    "32501,2021,14.82,310.5,310.5,205.1\n"
    "32501,2022,11.34,345.7,345.7,228.4\n"
    "32501,2023,4.10,359.9,359.9,237.8\n"
    "30310,2023,6.55,401.2,401.2,265.0\n"
)

FHFA_STATE_CSV = (
    "state,yr,qtr,index_nsa\n"
    "FL,2024,1,300.0\nFL,2024,2,305.0\nFL,2024,3,308.0\nFL,2024,4,310.0\nFL,2025,1,318.0\n"
    "GA,2024,1,200.0\nGA,2024,2,202.0\nGA,2024,3,203.0\nGA,2024,4,204.0\nGA,2025,1,206.0\n"
)


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def census_handler(payload, status=200):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handle


def csv_handler(text, status=200):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text)

    return handle


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Point the disk cache at a temp dir so tests never share state."""
    monkeypatch.setattr(md, "CACHE_DIR", tmp_path / "market-cache")


# --- Census ACS -----------------------------------------------------------


class TestCensusParsing:
    def test_maps_variables_by_name(self):
        context = md._context_from_row("32501", ACS_HEADER, ACS_ROW, "2023")
        assert context.median_home_value == 145_600.0
        assert context.median_gross_rent == 1_024.0
        assert context.median_year_built == 1962
        assert context.median_household_income == 41_250.0

    def test_derives_occupancy_and_vacancy_rates(self):
        context = md._context_from_row("32501", ACS_HEADER, ACS_ROW, "2023")
        assert context.owner_occupancy_rate == pytest.approx(1902 / 4210, abs=1e-4)
        assert context.vacancy_rate == pytest.approx(920 / 5130, abs=1e-4)

    def test_carries_the_margin_of_error(self):
        context = md._context_from_row("32501", ACS_HEADER, ACS_ROW, "2023")
        assert context.median_home_value_moe == 12_800.0

    def test_jam_values_become_none_not_negative_dollars(self):
        # -666666666 means "estimate not available". Reading it as a number is
        # the classic way to corrupt a Census integration.
        context = md._context_from_row("99999", ACS_HEADER, ACS_SUPPRESSED_ROW, "2023")
        assert context.median_home_value is None
        assert context.median_home_value_moe is None
        assert context.median_household_income is None

    def test_suppressed_value_is_disclosed_as_a_caveat(self):
        context = md._context_from_row("99999", ACS_HEADER, ACS_SUPPRESSED_ROW, "2023")
        assert any("no median home value" in caveat for caveat in context.caveats)

    def test_zcta_approximation_is_always_disclosed(self):
        context = md._context_from_row("32501", ACS_HEADER, ACS_ROW, "2023")
        assert any("ZIP Code Tabulation Area" in caveat for caveat in context.caveats)

    def test_a_wide_margin_of_error_is_flagged(self):
        row = list(ACS_ROW)
        row[ACS_HEADER.index("B25077_001M")] = "60000"  # 41% of the estimate
        context = md._context_from_row("32501", ACS_HEADER, row, "2023")
        assert any("wide margin of error" in caveat for caveat in context.caveats)

    def test_missing_variables_raise_a_schema_error(self):
        with pytest.raises(md.MarketDataSchemaError):
            md._context_from_row("32501", ["NAME", "zip code tabulation area"], ["x", "32501"], "2023")

    def test_mismatched_header_and_row_raise(self):
        with pytest.raises(md.MarketDataSchemaError):
            md._context_from_row("32501", ACS_HEADER, ACS_ROW[:-1], "2023")


class TestCensusFetch:
    def test_fetches_and_parses_a_live_shaped_response(self):
        client = mock_client(census_handler([ACS_HEADER, ACS_ROW]))
        context = md.fetch_market_context("32501", client=client, use_cache=False)
        assert context.median_home_value == 145_600.0
        assert context.vintage == "2023"
        assert context.as_dict()["provenance"]["api_key_required"] is False

    def test_an_area_with_no_data_is_unavailable_not_empty(self):
        # Census returns just the header for a ZCTA it does not publish.
        client = mock_client(census_handler([ACS_HEADER]))
        with pytest.raises(md.MarketDataUnavailable) as exc:
            md.fetch_market_context("00001", client=client, use_cache=False)
        assert "no ACS" in str(exc.value)

    def test_an_http_error_is_unavailable(self):
        client = mock_client(census_handler({}, status=503))
        with pytest.raises(md.MarketDataUnavailable):
            md.fetch_market_context("32501", client=client, use_cache=False)

    def test_a_proxy_block_explains_itself(self):
        client = mock_client(census_handler({}, status=403))
        with pytest.raises(md.MarketDataUnavailable) as exc:
            md.fetch_market_context("32501", client=client, use_cache=False)
        assert "egress proxy" in str(exc.value)

    def test_malformed_zip_is_rejected_before_any_request(self):
        for bad in ("1234", "abcde", "", "325011"):
            with pytest.raises(ValueError):
                md.fetch_market_context(bad)

    def test_results_are_cached_and_the_second_read_is_marked(self):
        calls = []

        def handle(request):
            calls.append(request.url)
            return httpx.Response(200, json=[ACS_HEADER, ACS_ROW])

        client = mock_client(handle)
        first = md.fetch_market_context("32501", client=client, use_cache=True)
        second = md.fetch_market_context("32501", client=client, use_cache=True)
        assert len(calls) == 1
        assert first.cached is False
        assert second.cached is True
        assert second.median_home_value == first.median_home_value

    def test_a_corrupt_cache_entry_does_not_break_the_fetch(self, tmp_path):
        md.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (md.CACHE_DIR / "acs-2023-32501.json").write_text("{not json")
        client = mock_client(census_handler([ACS_HEADER, ACS_ROW]))
        assert md.fetch_market_context("32501", client=client).median_home_value == 145_600.0


# --- FHFA -----------------------------------------------------------------


class TestFhfaParsing:
    def test_reads_the_latest_year_for_a_zip(self):
        rate, period = md.parse_fhfa_zip5(FHFA_ZIP5_CSV, "32501")
        assert rate == pytest.approx(0.041)
        assert period == "2023"

    def test_percentages_are_converted_to_fractions(self):
        rate, _ = md.parse_fhfa_zip5(FHFA_ZIP5_CSV, "30310")
        assert rate == pytest.approx(0.0655)

    def test_columns_are_located_by_name_not_position(self):
        reordered = "Year,Annual Change (%),Five-Digit ZIP Code\n2023,4.10,32501\n"
        assert md.parse_fhfa_zip5(reordered, "32501")[0] == pytest.approx(0.041)

    def test_an_unrecognised_header_fails_loudly(self):
        # Silently reading the wrong column would corrupt every time adjustment.
        with pytest.raises(md.MarketDataSchemaError):
            md.parse_fhfa_zip5("col_a,col_b\n1,2\n", "32501")

    def test_a_zip_with_no_index_is_unavailable(self):
        with pytest.raises(md.MarketDataUnavailable):
            md.parse_fhfa_zip5(FHFA_ZIP5_CSV, "11111")

    def test_quarterly_rate_is_year_over_year(self):
        # 318 / 300 - 1, comparing quarters four apart rather than consecutive
        # ones, which would pick up seasonality instead of appreciation.
        rate, period = md.parse_fhfa_periodic(
            FHFA_STATE_CSV, "FL", area_columns=("State", "state_abbr")
        )
        assert rate == pytest.approx(0.06)
        assert period == "2025Q1 vs 2024Q1"

    def test_areas_are_isolated_from_each_other(self):
        rate, _ = md.parse_fhfa_periodic(FHFA_STATE_CSV, "GA", area_columns=("State", "state_abbr"))
        assert rate == pytest.approx(0.03)

    def test_too_short_a_series_is_unavailable(self):
        short = "state,yr,qtr,index_nsa\nFL,2025,1,318.0\n"
        with pytest.raises(md.MarketDataUnavailable):
            md.parse_fhfa_periodic(short, "FL", area_columns=("State",))


class TestAppreciationResolution:
    def test_annual_to_monthly_compounds_correctly(self):
        monthly = md._annual_to_monthly(0.12)
        assert (1 + monthly) ** 12 == pytest.approx(1.12)

    def test_zip_level_is_preferred_and_marked_measured(self):
        client = mock_client(csv_handler(FHFA_ZIP5_CSV))
        rate = md.fetch_appreciation(zip_code="32501", client=client, use_cache=False)
        assert rate.measured is True
        assert rate.level == "zip"
        assert rate.annual_rate == pytest.approx(0.041)

    def test_falls_through_to_state_when_zip_is_absent(self):
        def handle(request):
            if "zip5" in str(request.url):
                return httpx.Response(200, text=FHFA_ZIP5_CSV)
            return httpx.Response(200, text=FHFA_STATE_CSV)

        client = mock_client(handle)
        rate = md.fetch_appreciation(
            zip_code="99999", state="FL", client=client, use_cache=False
        )
        assert rate.level == "state"
        assert rate.measured is True

    def test_the_fallback_is_never_presented_as_measured(self):
        client = mock_client(csv_handler("", status=403))
        rate = md.fetch_appreciation(zip_code="32501", client=client, use_cache=False)
        assert rate.measured is False
        assert rate.level == "fallback"
        assert "NOT measured" in rate.note

    def test_fallback_can_be_refused_when_a_caller_needs_real_data(self):
        client = mock_client(csv_handler("", status=403))
        with pytest.raises(md.MarketDataUnavailable):
            md.fetch_appreciation(
                zip_code="32501", client=client, use_cache=False, allow_fallback=False
            )

    def test_provenance_records_that_no_key_is_required(self):
        client = mock_client(csv_handler(FHFA_ZIP5_CSV))
        payload = md.fetch_appreciation(zip_code="32501", client=client, use_cache=False).as_dict()
        assert payload["provenance"]["api_key_required"] is False
        assert "public domain" in payload["provenance"]["licence"]


# --- Plausibility ---------------------------------------------------------


class TestPlausibility:
    def context(self, median=150_000.0, moe=5_000.0):
        return md.MarketContext(
            zip_code="32501", median_home_value=median, median_home_value_moe=moe, vintage="2023"
        )

    def test_a_typical_renovated_arv_is_consistent(self):
        result = md.check_arv_plausibility(180_000, self.context())
        assert result["verdict"] == "consistent"

    def test_a_decimal_error_is_caught(self):
        result = md.check_arv_plausibility(1_500_000, self.context())
        assert result["verdict"] == "implausible_high"
        assert "decimal" in result["guidance"]

    def test_an_all_distressed_comp_set_is_caught(self):
        result = md.check_arv_plausibility(30_000, self.context())
        assert result["verdict"] == "implausible_low"

    def test_a_renovated_premium_is_flagged_but_not_rejected(self):
        result = md.check_arv_plausibility(300_000, self.context())
        assert result["verdict"] == "high"

    def test_a_wide_census_margin_widens_the_acceptable_band(self):
        # A median known only to ±40% should not be used to reject an ARV that
        # a precise median would have rejected.
        precise = md.check_arv_plausibility(430_000, self.context(moe=2_000))
        imprecise = md.check_arv_plausibility(430_000, self.context(moe=60_000))
        assert precise["verdict"] == "implausible_high"
        assert imprecise["verdict"] != "implausible_high"

    def test_it_declines_to_check_without_a_published_median(self):
        result = md.check_arv_plausibility(200_000, self.context(median=None))
        assert result["checked"] is False
        assert "no median home value" in result["reason"]

    def test_it_states_that_it_is_a_screen_not_a_valuation(self):
        assert "not a valuation" in md.check_arv_plausibility(180_000, self.context())["note"]


class TestSourceRegistry:
    def test_every_source_declares_cost_licence_and_limits(self):
        for source in md.source_registry():
            assert source["cost"] == "free"
            assert source["api_key_required"] is False
            assert "public domain" in source["licence"]
            assert source["provides"]
            assert "individual sales" in source["does_not_provide"]

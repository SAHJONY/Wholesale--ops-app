"""Tests for the FEMA flood-risk connector.

Fixtures mirror the real wire formats: ArcGIS returns a ``features`` array (and
reports its own errors inside an HTTP 200 body), and OpenFEMA returns records
under a key named for the dataset.
"""

import httpx
import pytest

from app import flood_risk as fr
from app.market_data import MarketDataSchemaError, MarketDataUnavailable

# --- Fixtures -------------------------------------------------------------

NFHL_AE = {
    "features": [
        {
            "attributes": {
                "FLD_ZONE": "AE",
                "ZONE_SUBTY": None,
                "SFHA_TF": "T",
                "STATIC_BFE": 12.5,
                "DEPTH": -9999,
                "DFIRM_ID": "12033C",
            }
        }
    ]
}
NFHL_MINIMAL = {
    "features": [
        {
            "attributes": {
                "FLD_ZONE": "X",
                "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD",
                "SFHA_TF": "F",
                "STATIC_BFE": -9999,
                "DEPTH": -9999,
                "DFIRM_ID": "12033C",
            }
        }
    ]
}
# ArcGIS signals failure inside a 200 response.
NFHL_ERROR = {"error": {"code": 400, "message": "Invalid or missing input parameters."}}

GEOCODE_MATCH = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "12 OAK ST, PENSACOLA, FL, 32501",
                "coordinates": {"x": -87.2169, "y": 30.4213},
            }
        ]
    }
}

NFIP_CLAIMS = {
    "metadata": {"count": 3},
    "FimaNfipClaims": [
        {"yearOfLoss": 2023, "amountPaidOnBuildingClaim": 40000, "amountPaidOnContentsClaim": 5000},
        {"yearOfLoss": 2020, "amountPaidOnBuildingClaim": 18000, "amountPaidOnContentsClaim": 0},
        {"yearOfLoss": 2018, "amountPaidOnBuildingClaim": 12000, "amountPaidOnContentsClaim": 2000},
    ],
}
NFIP_POLICIES = {
    "metadata": {"count": 2},
    "FimaNfipPolicies": [
        {"totalInsurancePremiumOfThePolicy": 2000},
        {"totalInsurancePremiumOfThePolicy": 2300},
    ],
}


def client_for(routes):
    """Route by URL substring so one client can serve several endpoints."""

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for fragment, response in routes.items():
            if fragment in url:
                if isinstance(response, int):
                    return httpx.Response(response, json={})
                return httpx.Response(200, json=response)
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    from app import market_data

    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path / "flood-cache")


def zone_for(code, subtype=None, sfha=None, bfe=11.0):
    return fr._zone_from_attributes(
        {"FLD_ZONE": code, "ZONE_SUBTY": subtype, "SFHA_TF": sfha, "STATIC_BFE": bfe},
        30.4213,
        -87.2169,
    )


# --- Classification -------------------------------------------------------


class TestZoneClassification:
    @pytest.mark.parametrize("code", ["A", "AE", "AH", "AO", "AR", "A99"])
    def test_one_percent_zones_are_special_flood_hazard_areas(self, code):
        risk_class, in_sfha, _ = fr.classify_zone(code, None)
        assert in_sfha is True
        assert risk_class == "high"

    @pytest.mark.parametrize("code", ["V", "VE"])
    def test_coastal_zones_are_separated_from_ordinary_sfha(self, code):
        risk_class, in_sfha, _ = fr.classify_zone(code, None)
        assert risk_class == "coastal_high_hazard"
        assert in_sfha is True

    def test_shaded_x_is_moderate_and_plain_x_is_minimal(self):
        # Both are zone "X"; only the subtype separates the 0.2% floodplain from
        # genuinely minimal risk.
        moderate, _, _ = fr.classify_zone("X", "0.2 PCT ANNUAL CHANCE FLOOD HAZARD")
        minimal, _, _ = fr.classify_zone("X", "AREA OF MINIMAL FLOOD HAZARD")
        assert moderate == "moderate"
        assert minimal == "minimal"

    def test_zone_d_is_undetermined_not_safe(self):
        risk_class, in_sfha, description = fr.classify_zone("D", None)
        assert risk_class == "undetermined"
        assert in_sfha is False
        assert "not evidence of low risk" in description

    def test_an_unknown_code_is_undetermined_rather_than_assumed_safe(self):
        risk_class, _, description = fr.classify_zone("ZZZ", None)
        assert risk_class == "undetermined"
        assert "Unrecognised" in description


class TestAttributeParsing:
    def test_bfe_sentinel_becomes_none(self):
        # -9999 means "not applicable", not an elevation below sea level.
        assert zone_for("AE", bfe=-9999).base_flood_elevation is None
        assert zone_for("AE", bfe=12.5).base_flood_elevation == 12.5

    def test_femas_own_sfha_flag_overrides_zone_inference(self):
        assert zone_for("X", sfha="T").in_sfha is True
        assert zone_for("AE", sfha="F").in_sfha is False

    def test_zone_inference_is_used_when_the_flag_is_absent(self):
        assert zone_for("AE", sfha=None).in_sfha is True

    def test_map_currency_is_always_disclosed(self):
        caveats = " ".join(zone_for("AE").caveats)
        assert "effective FEMA map" in caveats
        assert "elevation certificate" in caveats


# --- Network paths --------------------------------------------------------


class TestFloodZoneLookup:
    def test_parses_a_live_shaped_response(self):
        client = client_for({"NFHL": NFHL_AE})
        zone = fr.lookup_flood_zone(30.4213, -87.2169, client=client, use_cache=False)
        assert zone.zone == "AE"
        assert zone.in_sfha is True
        assert zone.mandatory_insurance is True
        assert zone.base_flood_elevation == 12.5

    def test_an_arcgis_error_inside_a_200_is_not_treated_as_no_risk(self):
        # The failure mode that matters: a service error must never read as
        # "no flood hazard found".
        client = client_for({"NFHL": NFHL_ERROR})
        with pytest.raises(MarketDataUnavailable) as exc:
            fr.lookup_flood_zone(30.4213, -87.2169, client=client, use_cache=False)
        assert "NFHL error 400" in str(exc.value)

    def test_no_mapped_area_is_unavailable_not_low_risk(self):
        client = client_for({"NFHL": {"features": []}})
        with pytest.raises(MarketDataUnavailable) as exc:
            fr.lookup_flood_zone(30.4213, -87.2169, client=client, use_cache=False)
        assert "not the same as low risk" in str(exc.value)

    def test_a_missing_features_key_is_a_schema_error(self):
        client = client_for({"NFHL": {"unexpected": True}})
        with pytest.raises(MarketDataSchemaError):
            fr.lookup_flood_zone(30.4213, -87.2169, client=client, use_cache=False)

    def test_out_of_range_coordinates_are_rejected_before_any_request(self):
        for latitude, longitude in ((91.0, 0.0), (0.0, 181.0), (-91.0, 0.0)):
            with pytest.raises(ValueError):
                fr.lookup_flood_zone(latitude, longitude)

    def test_results_are_cached(self):
        calls = []

        def handle(request):
            calls.append(request.url)
            return httpx.Response(200, json=NFHL_AE)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        first = fr.lookup_flood_zone(30.4213, -87.2169, client=client)
        second = fr.lookup_flood_zone(30.4213, -87.2169, client=client)
        assert len(calls) == 1
        assert first.cached is False and second.cached is True


class TestGeocoding:
    def test_resolves_an_address_to_coordinates(self):
        client = client_for({"geocoder": GEOCODE_MATCH})
        result = fr.geocode_address("12 Oak St, Pensacola, FL", client=client)
        assert result.latitude == pytest.approx(30.4213)
        assert result.longitude == pytest.approx(-87.2169)
        assert "PENSACOLA" in result.matched_address

    def test_an_unmatched_address_is_unavailable(self):
        client = client_for({"geocoder": {"result": {"addressMatches": []}}})
        with pytest.raises(MarketDataUnavailable):
            fr.geocode_address("nowhere at all", client=client)

    def test_an_empty_address_is_rejected(self):
        with pytest.raises(ValueError):
            fr.geocode_address("   ")


class TestLossHistory:
    def test_summarises_claims_and_measures_the_premium(self):
        client = client_for({"FimaNfipClaims": NFIP_CLAIMS, "FimaNfipPolicies": NFIP_POLICIES})
        history = fr.fetch_flood_loss_history("32501", client=client)
        assert history.claim_count == 3
        assert history.total_paid == 77_000
        assert history.most_recent_loss_year == 2023
        assert history.average_annual_premium == pytest.approx(2150.0)

    def test_truncation_is_disclosed_rather_than_hidden(self):
        payload = dict(NFIP_CLAIMS, metadata={"count": 5000})
        client = client_for({"FimaNfipClaims": payload, "FimaNfipPolicies": NFIP_POLICIES})
        history = fr.fetch_flood_loss_history("32501", client=client)
        assert history.truncated is True
        assert any("understate" in caveat for caveat in history.caveats)

    def test_uninsured_losses_are_disclosed_as_invisible(self):
        client = client_for({"FimaNfipClaims": NFIP_CLAIMS, "FimaNfipPolicies": NFIP_POLICIES})
        history = fr.fetch_flood_loss_history("32501", client=client)
        assert any("uninsured" in caveat for caveat in history.caveats)

    def test_a_renamed_dataset_key_is_a_schema_error(self):
        client = client_for({"FimaNfipClaims": {"metadata": {}, "SomethingElse": []}})
        with pytest.raises(MarketDataSchemaError):
            fr.fetch_flood_loss_history("32501", client=client)

    def test_a_premium_outage_does_not_lose_the_claims(self):
        client = client_for({"FimaNfipClaims": NFIP_CLAIMS, "FimaNfipPolicies": 503})
        history = fr.fetch_flood_loss_history("32501", client=client)
        assert history.claim_count == 3
        assert history.average_annual_premium is None
        assert any("premium unavailable" in caveat.lower() for caveat in history.caveats)

    def test_a_malformed_zip_is_rejected(self):
        with pytest.raises(ValueError):
            fr.fetch_flood_loss_history("123")


# --- Underwriting impact --------------------------------------------------


class TestUnderwritingImpact:
    def history(self, premium=2150.0, claims=412):
        return fr.FloodLossHistory(
            zip_code="32501",
            claim_count=claims,
            claims_sampled=min(claims, 1000),
            total_paid=9_800_000,
            average_paid=23_786,
            most_recent_loss_year=2023,
            average_annual_premium=premium,
            policy_count=1_800,
            truncated=False,
        )

    def test_minimal_risk_zones_carry_no_value_impact(self):
        # Outside an SFHA coverage is optional and most buyers decline it, so
        # capitalising a premium there would invent a discount.
        assessment = fr.assess_flood_risk(
            zone_for("X", "AREA OF MINIMAL FLOOD HAZARD"), arv=250_000
        )
        assert assessment["insurance_take_up"] == 0.0
        assert assessment["capitalized_value_impact"] == 0.0

    def test_sfha_carries_a_material_impact(self):
        assessment = fr.assess_flood_risk(zone_for("AE"), arv=250_000)
        assert assessment["in_sfha"] is True
        assert assessment["capitalized_value_impact"] > 0
        assert 0.03 < assessment["value_impact_share_of_arv"] < 0.20

    def test_coastal_zones_cost_more_than_ordinary_sfha(self):
        coastal = fr.assess_flood_risk(zone_for("VE"), arv=250_000)
        ordinary = fr.assess_flood_risk(zone_for("AE"), arv=250_000)
        assert coastal["capitalized_value_impact"] > ordinary["capitalized_value_impact"]

    def test_a_measured_premium_is_labelled_as_measured(self):
        assessment = fr.assess_flood_risk(
            zone_for("AE"), arv=250_000, loss_history=self.history()
        )
        assert assessment["premium_measured"] is True
        assert assessment["estimated_annual_premium"] == 2150.0
        assert "OpenFEMA" in assessment["premium_basis"]

    def test_an_estimated_premium_is_never_presented_as_measured(self):
        assessment = fr.assess_flood_risk(zone_for("AE"), arv=250_000)
        assert assessment["premium_measured"] is False
        assert "not measured" in assessment["premium_basis"].lower()

    def test_an_outlier_premium_cannot_swamp_the_valuation(self):
        assessment = fr.assess_flood_risk(
            zone_for("VE"), arv=250_000, loss_history=self.history(premium=90_000)
        )
        assert assessment["value_impact_capped"] is True
        assert assessment["capitalized_value_impact"] <= 250_000 * fr.MAX_VALUE_IMPACT_SHARE

    def test_sfha_produces_actionable_verification_items(self):
        assessment = fr.assess_flood_risk(zone_for("AE"), arv=250_000)
        joined = " ".join(assessment["verification_required"]).lower()
        assert "elevation certificate" in joined
        assert "quote" in joined

    def test_realized_claims_are_surfaced_as_a_warning(self):
        assessment = fr.assess_flood_risk(
            zone_for("AE"), arv=250_000, loss_history=self.history()
        )
        assert any("412" in warning for warning in assessment["warnings"])

    def test_low_take_up_in_an_sfha_is_questioned(self):
        assessment = fr.assess_flood_risk(
            zone_for("AE"), arv=250_000, loss_history=self.history(claims=0)
        )
        assert any("take-up is simply low" in warning for warning in assessment["warnings"])

    def test_the_method_is_stated_rather_than_asserted(self):
        assessment = fr.assess_flood_risk(zone_for("AE"), arv=250_000)
        assert "not a FEMA or appraisal figure" in assessment["method"]


class TestSourceRegistry:
    def test_every_source_is_free_and_keyless(self):
        for source in fr.source_registry():
            assert source["cost"] == "free"
            assert source["api_key_required"] is False
            assert "public domain" in source["licence"]
            assert "individual sales" in source["does_not_provide"]

import asyncio

from app.nationwide_public_data import _extract_geography, _normalize_match, _terrain_context, build_truth_report


def test_normalize_census_match_extracts_geography():
    match = {
        "matchedAddress": "4600 SILVER HILL RD, WASHINGTON, DC, 20233",
        "coordinates": {"x": -76.9274, "y": 38.8459},
        "addressComponents": {"fromAddress": "4600", "streetName": "SILVER HILL", "suffixType": "RD", "city": "WASHINGTON", "state": "DC", "zip": "20233"},
        "geographies": {
            "States": [{"STATE": "11"}],
            "Counties": [{"STATE": "11", "COUNTY": "001", "GEOID": "11001", "NAME": "District of Columbia"}],
            "Census Tracts": [{"STATE": "11", "COUNTY": "001", "TRACT": "980000", "GEOID": "11001980000"}],
            "2020 Census Blocks": [{"BLOCK": "1000", "GEOID": "110019800001000"}],
        },
    }
    normalized = _normalize_match(match)
    assert normalized["matched_address"].startswith("4600")
    assert normalized["coordinates"]["latitude"] == 38.8459
    assert normalized["geography"]["county_geoid"] == "11001"
    assert normalized["geography"]["tract_geoid"] == "11001980000"
    assert normalized["geography"]["block_geoid"] == "110019800001000"


def test_extract_geography_tolerates_missing_layers():
    geography = _extract_geography({"geographies": {}})
    assert geography["state_fips"] is None
    assert geography["county_geoid"] is None


def test_nationwide_routes_are_registered():
    from api.index import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/public-data/nationwide/status" in paths
    assert "/public-data/nationwide/enrich-address" in paths


def test_truth_report_separates_verified_context_from_core_property_facts():
    report = build_truth_report(
        {
            "matched_address": "4600 SILVER HILL RD, WASHINGTON, DC, 20233",
            "coordinates": {"latitude": 38.8459, "longitude": -76.9274},
            "geography": {
                "county_name": "District of Columbia",
                "county_geoid": "11001",
                "tract_geoid": "11001980000",
            },
        },
        {"population": 671803, "median_gross_rent": 1770, "median_owner_value": 659400, "housing_units": 350364},
        "2026-07-31T12:00:00+00:00",
    )
    assert report["verified_claims"] == 10
    assert report["decision_gate"]["underwriting_ready"] is False
    assert report["decision_gate"]["outreach_ready"] is False
    assert {item["field"] for item in report["unknowns"]} >= {"legal_owner", "market_value_or_arv", "seller_contact_and_consent"}
    assert all(item["blocking"] for item in report["unknowns"])


def test_truth_report_marks_missing_aggregate_context_unavailable():
    report = build_truth_report(
        {"matched_address": "A", "coordinates": {}, "geography": {}},
        None,
        "2026-07-31T12:00:00+00:00",
    )
    population = next(item for item in report["claims"] if item["field"] == "population")
    assert population["status"] == "unavailable"
    assert population["confidence"] == "none"


def test_truth_report_includes_usgs_elevation_as_context_not_survey():
    report = build_truth_report(
        {"matched_address": "A", "coordinates": {}, "geography": {}},
        None,
        "2026-07-31T12:00:00+00:00",
        {"elevation_feet": 294.5},
    )
    elevation = next(item for item in report["claims"] if item["field"] == "ground_elevation_feet")
    assert elevation["status"] == "verified"
    assert elevation["source"] == "usgs_3dep"
    assert elevation["confidence"] == "interpolated_not_survey_grade"


def test_terrain_context_normalizes_usgs_response(monkeypatch):
    async def fake_request(url, params):
        return {"value": 294.519, "resolution": 1, "rasterId": 29928}, 88, 0

    monkeypatch.setattr("app.nationwide_public_data._request_json", fake_request)
    result = asyncio.run(_terrain_context(-76.9274, 38.8459))
    assert result == {
        "elevation_feet": 294.5,
        "dataset": "USGS 3D Elevation Program (3DEP)",
        "resolution_meters": 1,
        "raster_id": 29928,
        "latency_ms": 88,
        "retries": 0,
        "survey_grade": False,
    }

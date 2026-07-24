import pytest
from fastapi import HTTPException

from app.nationwide_public_data import _extract_geography, _normalize_match


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

from api.index import app
from app.live_public_enrichment import _parse_census_match


def test_live_public_enrichment_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/public-data/live-enrichment/status" in paths
    assert "/public-data/live-enrichment/run" in paths
    assert "get" in paths["/public-data/live-enrichment/status"]
    assert "post" in paths["/public-data/live-enrichment/run"]


def test_parse_census_match_preserves_geography_and_coordinates():
    payload = {
        "result": {
            "addressMatches": [{
                "matchedAddress": "123 MAIN ST, PENSACOLA, FL, 32501",
                "coordinates": {"x": -87.2, "y": 30.4},
                "tigerLine": {"tigerLineId": "42"},
                "geographies": {
                    "Counties": [{"NAME": "Escambia County"}],
                    "Census Tracts": [{"TRACT": "000100"}],
                    "2020 Census Blocks": [{"BLOCK": "1000"}],
                },
            }]
        }
    }
    match = _parse_census_match(payload)
    assert match is not None
    assert match["latitude"] == 30.4
    assert match["longitude"] == -87.2
    assert match["county"]["NAME"] == "Escambia County"
    assert match["tiger_line_id"] == "42"


def test_parse_census_match_returns_none_for_no_match():
    assert _parse_census_match({"result": {"addressMatches": []}}) is None

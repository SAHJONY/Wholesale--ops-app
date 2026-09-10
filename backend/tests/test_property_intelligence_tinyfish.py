from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.index import app
from app.tinyfish_intelligence import _goal, _output_schema, _validate_source_url

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_property_intelligence_and_tinyfish_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "get" in paths["/property-intelligence/globe"]
    assert "get" in paths["/tinyfish/status"]
    assert "post" in paths["/tinyfish/research"]


def test_tinyfish_source_validation_is_https_and_allowlist_only():
    allowed = ("escambiaclerk.com", "pa.escambia.fl.us")
    assert _validate_source_url("https://records.escambiaclerk.com/case/1", allowed).startswith("https://")

    for blocked in (
        "http://records.escambiaclerk.com/case/1",
        "https://127.0.0.1/private",
        "https://example.com/property/1",
        "https://user:password@records.escambiaclerk.com/case/1",
        "https://records.escambiaclerk.com:8443/case/1",
        "https://records.escambiaclerk.com/case/1?access_token=secret",
    ):
        with pytest.raises(HTTPException):
            _validate_source_url(blocked, allowed)


def test_tinyfish_schema_and_goal_prohibit_contact_collection():
    schema_text = str(_output_schema()).lower()
    assert "phone" not in schema_text
    assert "email" not in schema_text
    assert "relative" not in schema_text
    item = SimpleNamespace(address="123 Main St", city="Pensacola", state="FL", zip_code="32501")
    goal = _goal(item, "court_docket").lower()
    assert "do not collect phone numbers" in goal
    assert "minors" in goal
    assert "do not infer ownership" in goal


def test_property_map_contract_is_privacy_scoped_and_excludes_texas():
    source = read("backend/app/property_intelligence_map.py")
    page = read("frontend/app/owner/property-map/page.tsx")
    assert '"contact_data_exposed": False' in source
    assert '"owner_identity_exposed": False' in source
    assert '"texas_excluded": True' in source
    assert '"single_family_only": True' in source
    assert "seller_name" not in source
    assert "seller.phone" not in source
    assert "TinyFish may navigate only allowlisted public domains" in page
    assert "never update property truth automatically" in page


def test_tinyfish_provider_is_visible_in_integration_control_plane():
    source = read("backend/app/integration_hub.py")
    assert '"id": "tinyfish"' in source
    assert '"research_preview_only"' in source
    assert '"public_web_research": ready("tinyfish")' in source

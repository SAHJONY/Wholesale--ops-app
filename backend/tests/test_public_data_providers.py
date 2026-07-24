import pytest
from fastapi import HTTPException

from app.public_data_providers import PUBLIC_DATA_PROVIDERS, canonical_preview, provider_status


def test_catalog_contains_required_public_and_licensed_sources(monkeypatch):
    ids = {item["id"] for item in PUBLIC_DATA_PROVIDERS}
    assert {
        "county_recorder", "county_assessor", "tax_delinquent", "code_violations",
        "probate", "foreclosure_public", "building_permits", "municipal_open_data", "fema_national",
        "census", "epa", "openaddresses", "usps_vacancy", "mls_idx",
    }.issubset(ids)
    licensed = {item["id"] for item in PUBLIC_DATA_PROVIDERS if item["license_required"]}
    assert licensed == {"usps_vacancy", "mls_idx"}


def test_sources_default_disabled_and_dry_run_safe(monkeypatch):
    provider = next(item for item in PUBLIC_DATA_PROVIDERS if item["id"] == "county_recorder")
    monkeypatch.delenv(provider["feature_flag"], raising=False)
    monkeypatch.delenv(provider["endpoint_env"], raising=False)
    result = provider_status(provider)
    assert result["state"] == "disabled"
    assert result["outbound_capable"] is False
    assert result["dry_run_safe"] is True


def test_enabled_jurisdiction_source_requires_endpoint(monkeypatch):
    provider = next(item for item in PUBLIC_DATA_PROVIDERS if item["id"] == "county_assessor")
    monkeypatch.setenv(provider["feature_flag"], "true")
    monkeypatch.delenv(provider["endpoint_env"], raising=False)
    assert provider_status(provider)["state"] == "enabled_missing_endpoint"
    monkeypatch.setenv(provider["endpoint_env"], "https://example.gov/assessor")
    assert provider_status(provider)["state"] == "configured"


def test_canonical_preview_preserves_provenance_and_blocks_actions():
    result = canonical_preview("county_recorder", {
        "id": "deed-1", "address": "100 Main St", "city": "Miami", "state": "FL",
        "zip": "33101", "apn": "12-34", "owner": "Example Owner",
    })
    assert result["provider_record_id"] == "deed-1"
    assert result["parcel_id"] == "12-34"
    assert result["source"]["provider_id"] == "county_recorder"
    assert result["workflow"] == {
        "dry_run": True,
        "external_actions_allowed": False,
        "owner_review_required": True,
    }


def test_canonical_preview_enforces_texas_exclusion():
    with pytest.raises(HTTPException) as exc:
        canonical_preview("county_assessor", {"state": "TX"})
    assert exc.value.status_code == 409


def test_nationwide_public_routes_are_in_openapi():
    from api.index import app

    schema = app.openapi()
    assert "/public-data/nationwide/status" in schema["paths"]
    assert "/public-data/nationwide/enrich-address" in schema["paths"]

import os

import pytest
from fastapi import HTTPException

from app.public_data_providers import PUBLIC_DATA_PROVIDERS, canonical_preview, provider_status


REQUIRED_PROVIDER_IDS = {
    "county_recorder",
    "county_assessor",
    "tax_delinquent",
    "code_violations",
    "probate",
    "foreclosure_public",
    "building_permits",
    "municipal_open_data",
    "fema_national",
    "census",
    "epa",
    "openaddresses",
    "usps_vacancy",
    "mls_idx",
}


def test_required_provider_catalog_is_complete():
    assert REQUIRED_PROVIDER_IDS <= {item["id"] for item in PUBLIC_DATA_PROVIDERS}


def test_all_providers_default_disabled(monkeypatch):
    for provider in PUBLIC_DATA_PROVIDERS:
        monkeypatch.delenv(provider["feature_flag"], raising=False)
        monkeypatch.delenv(provider["endpoint_env"], raising=False)
        status = provider_status(provider)
        assert status["enabled"] is False
        assert status["state"] == "disabled"
        assert status["outbound_capable"] is False
        assert status["dry_run_safe"] is True


def test_jurisdiction_provider_requires_endpoint(monkeypatch):
    provider = next(item for item in PUBLIC_DATA_PROVIDERS if item["id"] == "county_recorder")
    monkeypatch.setenv(provider["feature_flag"], "true")
    monkeypatch.delenv(provider["endpoint_env"], raising=False)
    assert provider_status(provider)["state"] == "enabled_missing_endpoint"


def test_canonical_preview_preserves_provenance_and_dry_run():
    preview = canonical_preview("county_assessor", {
        "id": "parcel-1",
        "address": "100 Main St",
        "city": "Pensacola",
        "state": "FL",
        "zip": "32501",
        "apn": "123-456",
        "owner": "Sample Owner",
        "assessed_value": 150000,
    })
    assert preview["provider_record_id"] == "parcel-1"
    assert preview["parcel_id"] == "123-456"
    assert preview["source"]["provider_id"] == "county_assessor"
    assert preview["workflow"]["dry_run"] is True
    assert preview["workflow"]["external_actions_allowed"] is False


def test_texas_is_rejected():
    with pytest.raises(HTTPException) as exc:
        canonical_preview("county_assessor", {"state": "TX", "address": "1 Main St"})
    assert exc.value.status_code == 409


def test_nationwide_public_routes_are_in_openapi():
    from api.index import app

    schema = app.openapi()
    assert "/public-data/nationwide/status" in schema["paths"]
    assert "/public-data/nationwide/enrich-address" in schema["paths"]

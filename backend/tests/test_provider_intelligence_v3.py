from pathlib import Path

from app.providers.batchdata import BatchDataConfig, canonicalize_lookup


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_batchdata_config_prefers_sandbox(monkeypatch):
    monkeypatch.setenv("BATCHDATA_API_KEY", "production-secret")
    monkeypatch.setenv("BATCHDATA_SANDBOX_API_KEY", "sandbox-secret")
    monkeypatch.setenv("BATCHDATA_PROPERTY_LOOKUP_URL", "https://example.test/property/lookup")

    config = BatchDataConfig.from_env()

    assert config is not None
    assert config.api_key == "sandbox-secret"
    assert config.environment == "sandbox"
    assert config.lookup_url.startswith("https://")


def test_batchdata_canonicalizer_adds_field_level_provenance():
    canonical = canonicalize_lookup({
        "environment": "sandbox",
        "request_id": "request-123",
        "observed_at": "2026-08-01T12:00:00+00:00",
        "http_status": 200,
        "raw": {
            "results": [{
                "property": {"parcelNumber": "ABC"},
                "owner": {"name": "Example Owner"},
                "valuation": {"value": 250000},
                "contacts": [{"phone": "redacted-in-ui"}],
                "mortgages": [],
                "liens": [],
                "comparables": [],
            }]
        },
    })

    assert canonical["property"]["parcelNumber"] == "ABC"
    assert canonical["owner"]["name"] == "Example Owner"
    assert canonical["provider"]["request_id"] == "request-123"
    assert canonical["field_provenance"]["owner"]["provider_id"] == "batchdata"
    assert canonical["confidence"] == 0.90


def test_provider_intelligence_v3_is_preview_first_and_fail_closed():
    source = read("backend/app/provider_intelligence.py")
    adapter = read("backend/app/providers/batchdata.py")
    page = read("frontend/app/owner/live-data/page.tsx")

    assert '"version": "3.0"' in source
    assert "field_level_provenance" in source
    assert "contact_data_redacted_by_default" in source
    assert "dnc_tcpa_screening_required" in source
    assert "external_offer_allowed" in source
    assert "contact_data_committed\":False" in source
    assert "BATCHDATA_PROPERTY_LOOKUP_URL" in adapter
    assert "BATCHDATA_SANDBOX_API_KEY" in adapter
    assert "follow_redirects=False" in adapter
    assert "include_contacts:false" in page
    assert "Provider data is evidence, not automatic authority" in page

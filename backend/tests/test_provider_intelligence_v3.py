from pathlib import Path

from app.providers import batchdata
from app.providers.batchdata import BatchDataConfig, canonicalize_lookup, lookup_property, verify_credentials


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_batchdata_config_uses_mcp_and_stable_callback(monkeypatch):
    monkeypatch.setenv("BATCHDATA_MCP_URL", "https://mcp.batchdata.com")
    monkeypatch.setenv("BATCHDATA_OAUTH_CALLBACK_BASE_URL", "https://backend.example.test")

    config = BatchDataConfig.from_env()

    assert config is not None
    assert config.mcp_url == "https://mcp.batchdata.com"
    assert config.redirect_uri == "https://backend.example.test/provider-intelligence/batchdata/callback"


def test_batchdata_verification_lists_tools_without_property_query(monkeypatch):
    config = BatchDataConfig("https://mcp.batchdata.com", "https://backend.example.test")
    monkeypatch.setattr(batchdata, "_access_token", lambda *args: "oauth-access")
    monkeypatch.setattr(batchdata, "_mcp_exchange", lambda *args: ({"tools": [{"name": "lookup_property"}]}, "session-1"))

    result = verify_credentials(config, object(), 7)

    assert result["state"] == "ready_verified"
    assert result["verified"] is True
    assert result["tool"] == "lookup_property"
    assert result["contacts_exposed"] is False


def test_batchdata_verification_refreshes_once_after_unauthorized(monkeypatch):
    config = BatchDataConfig("https://mcp.batchdata.com", "https://backend.example.test")
    calls = []
    monkeypatch.setattr(batchdata, "_access_token", lambda *args: "expired-access")
    monkeypatch.setattr(batchdata, "_force_refresh", lambda *args: "refreshed-access")

    def exchange(config, token, method, params, request_id):
        calls.append(token)
        if token == "expired-access":
            raise batchdata.BatchDataProviderError("invalid_credentials", "expired", 401)
        return {"tools": [{"name": "lookup_property"}]}, "session-1"

    monkeypatch.setattr(batchdata, "_mcp_exchange", exchange)

    result = verify_credentials(config, object(), 7)

    assert calls == ["expired-access", "refreshed-access"]
    assert result["verified"] is True


def test_batchdata_lookup_calls_official_mcp_tool_arguments(monkeypatch):
    captured = {}
    config = BatchDataConfig("https://mcp.batchdata.com", "https://backend.example.test")
    monkeypatch.setattr(batchdata, "_access_token", lambda *args: "oauth-access")

    def exchange(config, token, method, params, request_id):
        captured.update({"method": method, "params": params})
        return {"structuredContent": {"property": {"parcelNumber": "ABC"}}}, "session-1"

    monkeypatch.setattr(batchdata, "_mcp_exchange", exchange)
    result = lookup_property(config, object(), 7, {
        "street": "123 Main St", "city": "Pensacola", "state": "FL", "zip": "32501",
    })

    assert captured["method"] == "tools/call"
    assert captured["params"]["name"] == "lookup_property"
    assert captured["params"]["arguments"] == {
        "property_street": "123 Main St",
        "property_city": "Pensacola",
        "property_state": "FL",
        "property_zip": "32501",
    }
    assert result["raw"]["property"]["parcelNumber"] == "ABC"
    assert result["environment"] == "oauth_mcp"


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

    assert '"version": "4.0"' in source
    assert "field_level_provenance" in source
    assert "contact_data_redacted_by_default" in source
    assert "dnc_tcpa_screening_required" in source
    assert "external_offer_allowed" in source
    assert "contact_data_committed\":False" in source
    assert "BATCHDATA_MCP_URL" in adapter
    assert "BATCHDATA_OAUTH_ENCRYPTION_KEY" in adapter
    assert 'MCP_TOOL_NAME = "lookup_property"' in adapter
    assert '"property_street"' in adapter
    assert '"tools/call"' in adapter
    assert "code_challenge_method" in adapter
    assert "follow_redirects=False" in adapter
    assert "include_contacts:false" in page
    assert "PROVIDER INTELLIGENCE V4" in page
    assert "Canonical Property Intelligence" in page
    assert "Provider data is evidence, not automatic authority" in page

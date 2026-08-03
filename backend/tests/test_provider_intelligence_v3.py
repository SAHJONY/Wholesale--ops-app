from pathlib import Path

from app.providers import batchdata
from app.providers.batchdata import BatchDataConfig, canonicalize_lookup, lookup_property, verify_credentials


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_batchdata_config_uses_mcp_and_server_token(monkeypatch):
    monkeypatch.setenv("BATCHDATA_MCP_URL", "https://mcp.batchdata.com")
    monkeypatch.setenv("BATCHDATA_API_TOKEN", "server-token")

    config = BatchDataConfig.from_env()

    assert config is not None
    assert config.mcp_url == "https://mcp.batchdata.com"
    assert config.api_token == "server-token"


def test_batchdata_verification_lists_tools_without_property_query(monkeypatch):
    config = BatchDataConfig("https://mcp.batchdata.com", "server-token")
    monkeypatch.setattr(batchdata, "_mcp_exchange", lambda *args: ({"tools": [{"name": "lookup_property"}]}, "session-1"))

    result = verify_credentials(config, object(), 7)

    assert result["state"] == "ready_verified"
    assert result["verified"] is True
    assert result["tool"] == "lookup_property"
    assert result["contacts_exposed"] is False


def test_batchdata_verification_fails_closed_after_unauthorized(monkeypatch):
    config = BatchDataConfig("https://mcp.batchdata.com", "bad-server-token")
    monkeypatch.setattr(
        batchdata,
        "_mcp_exchange",
        lambda *args: (_ for _ in ()).throw(
            batchdata.BatchDataProviderError("invalid_credentials", "expired", 401)
        ),
    )

    result = verify_credentials(config, object(), 7)

    assert result["state"] == "invalid_credentials"
    assert result["verified"] is False
    assert result["http_status"] == 401


def test_batchdata_lookup_calls_official_mcp_tool_arguments(monkeypatch):
    captured = {}
    config = BatchDataConfig("https://mcp.batchdata.com", "server-token")

    def exchange(config, method, params, request_id):
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
    assert result["environment"] == "server_token_mcp"


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


def test_provider_intelligence_v4_is_preview_first_and_fail_closed():
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
    assert "BATCHDATA_API_TOKEN" in adapter
    assert 'MCP_TOOL_NAME = "lookup_property"' in adapter
    assert '"property_street"' in adapter
    assert '"tools/call"' in adapter
    assert '"Authorization": f"Bearer {config.api_token}"' in adapter
    assert "follow_redirects=False" in adapter
    assert "BATCHDATA_OAUTH_ENCRYPTION_KEY" not in adapter
    assert "Connect OAuth" not in page
    assert "include_contacts:false" in page
    assert "PROVIDER INTELLIGENCE V4" in page
    assert "Canonical Property Intelligence" in page
    assert "Provider data is evidence, not automatic authority" in page

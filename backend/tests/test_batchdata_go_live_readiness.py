from pathlib import Path

from app.go_live import PROVIDER_GROUPS, _configured


ROOT = Path(__file__).resolve().parents[2]
OBSOLETE_PROPERTY_LOOKUP_ENV = {
    "BATCHDATA_" + "PROPERTY_LOOKUP_URL",
    "BATCHDATA_" + "SANDBOX_API_KEY",
    "BATCHDATA_" + "TEST_ADDRESS",
}


def test_batchdata_mcp_and_skip_trace_have_distinct_readiness(monkeypatch):
    for name in PROVIDER_GROUPS["property_intelligence_mcp"] + PROVIDER_GROUPS["contact_enrichment"]:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("BATCHDATA_MCP_URL", "https://mcp.batchdata.com")
    monkeypatch.setenv("BATCHDATA_API_TOKEN", "server-token")

    assert _configured(PROVIDER_GROUPS["property_intelligence_mcp"])
    assert not _configured(PROVIDER_GROUPS["contact_enrichment"])

    monkeypatch.setenv("BATCHDATA_SKIPTRACE_URL", "https://example.test/skip-trace")
    monkeypatch.setenv("BATCHDATA_API_KEY", "rest-api-key")

    assert _configured(PROVIDER_GROUPS["contact_enrichment"])


def test_obsolete_property_lookup_variables_are_not_documented_or_used():
    paths = [ROOT / "README.md", ROOT / "backend" / "app", ROOT / "backend" / "tests"]
    source = "\n".join(
        path.read_text()
        for root in paths
        for path in ([root] if root.is_file() else root.rglob("*.py"))
    )

    for name in OBSOLETE_PROPERTY_LOOKUP_ENV:
        assert name not in source

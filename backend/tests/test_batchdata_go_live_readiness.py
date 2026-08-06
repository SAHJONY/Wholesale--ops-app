from pathlib import Path

from app import provider_requirements as pr


ROOT = Path(__file__).resolve().parents[2]
OBSOLETE_PROPERTY_LOOKUP_ENV = {
    "BATCHDATA_" + "PROPERTY_LOOKUP_URL",
    "BATCHDATA_" + "SANDBOX_API_KEY",
    "BATCHDATA_" + "TEST_ADDRESS",
}


def test_batchdata_mcp_and_skip_trace_have_distinct_readiness(monkeypatch):
    # Two BatchData products behind one vendor name. Configuring the MCP
    # transport says nothing about whether skip tracing will work, and treating
    # them as one credential meant a contact lookup failing on a checklist that
    # reported the vendor connected.
    for requirement in ("property_intelligence_mcp", "contact_enrichment"):
        for group in pr.BY_ID[requirement].alternatives:
            for name in group:
                monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("BATCHDATA_MCP_URL", "https://mcp.batchdata.com")
    monkeypatch.setenv("BATCHDATA_API_TOKEN", "server-token")

    assert pr.ready("property_intelligence_mcp")
    assert not pr.ready("contact_enrichment")

    monkeypatch.setenv("BATCHDATA_SKIPTRACE_URL", "https://example.test/skip-trace")
    monkeypatch.setenv("BATCHDATA_API_KEY", "rest-api-key")

    assert pr.ready("contact_enrichment")


def test_obsolete_property_lookup_variables_are_not_documented_or_used():
    paths = [ROOT / "README.md", ROOT / "backend" / "app", ROOT / "backend" / "tests"]
    source = "\n".join(
        path.read_text()
        for root in paths
        for path in ([root] if root.is_file() else root.rglob("*.py"))
    )

    for name in OBSOLETE_PROPERTY_LOOKUP_ENV:
        assert name not in source

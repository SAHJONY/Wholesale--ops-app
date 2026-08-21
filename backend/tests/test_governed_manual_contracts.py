from pathlib import Path

from app.deal_execution import _manual_contracts_ready, _provider_readiness


ROOT = Path(__file__).resolve().parents[2]


def test_manual_contracts_require_explicit_mode_and_private_blob(monkeypatch):
    monkeypatch.delenv("CONTRACT_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)

    assert _manual_contracts_ready() is False

    monkeypatch.setenv("CONTRACT_EXECUTION_MODE", "manual_governed")
    assert _manual_contracts_ready() is False

    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    assert _manual_contracts_ready() is True


def test_manual_contracts_satisfy_selected_provider_readiness(monkeypatch):
    monkeypatch.setenv("E_SIGNATURE_PROVIDER", "manual")
    monkeypatch.setenv("CONTRACT_EXECUTION_MODE", "manual_governed")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    monkeypatch.delenv("DOCUSEAL_API_KEY", raising=False)
    monkeypatch.delenv("DOCUSEAL_URL", raising=False)

    readiness = _provider_readiness()

    assert readiness["selected_provider"] == "manual"
    assert readiness["provider_configured"] is True
    assert readiness["manual_governed_configured"] is True
    assert readiness["document_storage"] is True


def test_manual_completion_requires_private_blob_document_url():
    source = (ROOT / "backend" / "app" / "deal_execution.py").read_text()

    assert '@router.post("/packets/{packet_id}/manual-completion")' in source
    assert '".blob.vercel-storage.com/" not in storage_key' in source
    assert 'verification_method": "owner_attestation"' in source

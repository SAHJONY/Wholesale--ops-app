import json

import pytest
from fastapi import HTTPException

from app import internal_voice_service as service
from app.agentic_voice_brain import SAFE_TOOL_NAMES


def test_service_signature_round_trip(monkeypatch):
    monkeypatch.setenv("OPENAI_WEBHOOK_SECRET", "whsec_test_secret")
    body = json.dumps({"organization_id": 1, "tool_name": "get_lead_context", "arguments": {"lead_id": 4}}, separators=(",", ":")).encode()
    timestamp = "1786778000"
    signature = service.service_signature(timestamp, body)
    service.verify_service_signature(timestamp, signature, body, now=1786778000)


def test_tampered_body_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_WEBHOOK_SECRET", "whsec_test_secret")
    original = b'{"organization_id":1,"tool_name":"get_lead_context","arguments":{"lead_id":4}}'
    signature = service.service_signature("1786778000", original)
    with pytest.raises(HTTPException) as exc:
        service.verify_service_signature("1786778000", signature, original + b" ", now=1786778000)
    assert exc.value.status_code == 401


def test_expired_service_signature_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_WEBHOOK_SECRET", "whsec_test_secret")
    body = b"{}"
    signature = service.service_signature("1786777000", body)
    with pytest.raises(HTTPException) as exc:
        service.verify_service_signature("1786777000", signature, body, now=1786778000)
    assert exc.value.status_code == 401


def test_missing_webhook_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("OPENAI_WEBHOOK_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        service.service_signature("1786778000", b"{}")
    assert exc.value.status_code == 503


def test_inbound_resolution_is_safe_but_consequential_tools_remain_absent():
    assert "resolve_lead_by_phone" in SAFE_TOOL_NAMES
    for name in ("binding_offer", "contract_execution", "money_movement", "title_clearance", "autonomous_outbound_dispatch"):
        assert name not in SAFE_TOOL_NAMES

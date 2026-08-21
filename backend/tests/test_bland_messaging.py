import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.bland_messaging import verify_bland_signature
from app.outbound_gateway import _validate_channel_provider, bland_sms_agent_number


def test_sms_and_voice_use_bland_only():
    _validate_channel_provider("sms", "bland")
    _validate_channel_provider("automated_call", "bland")

    with pytest.raises(HTTPException) as exc:
        _validate_channel_provider("sms", "twilio")
    assert exc.value.status_code == 422
    assert "sms/bland" in str(exc.value.detail)


def test_bland_sms_agent_number_uses_messaging_number(monkeypatch):
    monkeypatch.delenv("BLAND_SMS_AGENT_NUMBER", raising=False)
    monkeypatch.setenv("BLAND_MESSAGING_NUMBER", "+15551234567")
    assert bland_sms_agent_number() == "+15551234567"


def test_bland_sms_agent_number_rejects_non_e164(monkeypatch):
    monkeypatch.setenv("BLAND_SMS_AGENT_NUMBER", "(555) 123-4567")
    with pytest.raises(HTTPException) as exc:
        bland_sms_agent_number()
    assert exc.value.status_code == 503
    assert "E.164" in str(exc.value.detail)


def test_bland_webhook_signature_accepts_exact_hmac(monkeypatch):
    secret = "test-bland-signing-secret"
    body = b'{"channel":"sms","sender":"USER","message":"hello"}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("BLAND_WEBHOOK_SIGNING_SECRET", secret)

    verify_bland_signature(body, signature)


def test_bland_webhook_signature_rejects_tampered_body(monkeypatch):
    secret = "test-bland-signing-secret"
    body = b'{"channel":"sms","sender":"USER","message":"hello"}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("BLAND_WEBHOOK_SIGNING_SECRET", secret)

    with pytest.raises(HTTPException) as exc:
        verify_bland_signature(body + b" ", signature)
    assert exc.value.status_code == 401

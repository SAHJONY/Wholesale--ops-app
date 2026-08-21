import hashlib
import hmac

from app import bland_phone_system as bland
from app.models import Lead


def test_bland_webhook_signature_uses_raw_body_hmac(monkeypatch):
    secret = "test-signing-secret"
    body = b'{"call_id":"call-123"}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", secret)

    assert bland._verify_signature(body, signature)
    assert not bland._verify_signature(body + b" ", signature)


def test_bland_inbound_numbers_support_callback_inventory(monkeypatch):
    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+13465214387, +12164804413")

    assert bland._inbound_numbers() == ("+13465214387", "+12164804413")


def test_bland_outbound_task_discloses_ai_and_forbids_binding_offer():
    lead = Lead(id=1, seller_name="Jordan")
    task = bland._safe_task(lead)

    assert "automated voice assistant" in task
    assert "Ask permission to continue" in task
    assert "Never make a binding offer" in task
    assert "mark opt-out" in task


def test_bland_autonomous_outbound_defaults_off(monkeypatch):
    monkeypatch.delenv("BLAND_AUTONOMOUS_OUTBOUND_ENABLED", raising=False)

    assert bland._enabled("BLAND_AUTONOMOUS_OUTBOUND_ENABLED", False) is False

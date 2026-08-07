import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")
os.environ.setdefault("BLAND_AI_API_KEY", "test-key")

from app import outbound_gateway as og
from app.outbound_gateway import DECISION_TTL, _decision_for_request, _validate_channel_provider
from app.outbound_models import OutboundRequest


class FakeDb:
    def __init__(self, decision):
        self.decision = decision

    def get(self, _model, _identifier):
        return self.decision


def principal():
    return SimpleNamespace(organization_id=7, user_id=3)


def decision(**overrides):
    base = {
        "organization_id": 7,
        "lead_id": 11,
        "channel": "sms",
        "contact": "+13055551212",
        "allowed": True,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_supported_provider_pairs():
    _validate_channel_provider("sms", "bland")
    _validate_channel_provider("automated_call", "bland")
    with pytest.raises(HTTPException):
        _validate_channel_provider("sms", "twilio")


def test_exact_decision_match_is_required():
    record = decision()
    resolved = _decision_for_request(FakeDb(record), principal(), 11, 1, "sms", "+13055551212")
    assert resolved is record
    with pytest.raises(HTTPException):
        _decision_for_request(FakeDb(record), principal(), 11, 1, "sms", "+13055550000")


def test_blocked_decision_cannot_dispatch():
    with pytest.raises(HTTPException):
        _decision_for_request(FakeDb(decision(allowed=False)), principal(), 11, 1, "sms", "+13055551212")


def test_decision_expires_after_fifteen_minutes():
    stale = decision(created_at=datetime.now(timezone.utc) - DECISION_TTL - timedelta(seconds=1))
    with pytest.raises(HTTPException):
        _decision_for_request(FakeDb(stale), principal(), 11, 1, "sms", "+13055551212")


def test_cross_workspace_decision_is_rejected():
    with pytest.raises(HTTPException):
        _decision_for_request(FakeDb(decision(organization_id=99)), principal(), 11, 1, "sms", "+13055551212")


# ------------------------------------------------------------- caller ID --

def test_a_plain_e164_number_is_accepted(monkeypatch):
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    assert og.caller_id() == "+13465214387"


def test_typographic_quotes_are_rejected_with_a_useful_message(monkeypatch):
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "“+13465214387”")
    with pytest.raises(HTTPException) as raised:
        og.caller_id()
    assert "E.164" in str(raised.value.detail)


def test_common_formatting_mistakes_are_rejected(monkeypatch):
    for value in ('"+13465214387"', "+1 346 521 4387", "+1-346-521-4387",
                  "13465214387", "(346) 521-4387"):
        monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", value)
        with pytest.raises(HTTPException):
            og.caller_id()


def test_caller_id_falls_back_to_the_second_name(monkeypatch):
    monkeypatch.delenv("BLAND_DEFAULT_FROM_NUMBER", raising=False)
    monkeypatch.setenv("BLAND_DEFAULT_CALLER_ID", "+12164804413")
    assert og.caller_id() == "+12164804413"


def test_the_from_number_wins_when_both_are_set(monkeypatch):
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    monkeypatch.setenv("BLAND_DEFAULT_CALLER_ID", "+12164804413")
    assert og.caller_id() == "+13465214387"


def test_no_configured_caller_id_is_not_an_error(monkeypatch):
    monkeypatch.delenv("BLAND_DEFAULT_FROM_NUMBER", raising=False)
    monkeypatch.delenv("BLAND_DEFAULT_CALLER_ID", raising=False)
    assert og.caller_id() is None


def test_sms_uses_a_bland_messaging_number(monkeypatch):
    monkeypatch.delenv("BLAND_SMS_AGENT_NUMBER", raising=False)
    monkeypatch.delenv("BLAND_MESSAGING_NUMBER", raising=False)
    monkeypatch.delenv("BLAND_DEFAULT_FROM_NUMBER", raising=False)
    monkeypatch.delenv("BLAND_DEFAULT_CALLER_ID", raising=False)

    request = call_request(body="Hi, it's Sam with SAHJONY. Reply STOP to opt out.")
    request.channel, request.provider = "sms", "bland"
    with pytest.raises(HTTPException) as raised:
        asyncio.run(og._dispatch_bland_sms(request))
    assert raised.value.status_code == 503
    assert "SMS agent number" in str(raised.value.detail)


# ------------------------------------------- the AI-disclosure gate on calls --

class DispatchDb:
    """Just enough database to drive the dispatch endpoint."""

    def __init__(self, request, lead):
        self.request, self.lead = request, lead
        self.added = []
        self.committed = False

    def get(self, model, _identifier):
        return self.request if model is OutboundRequest else self.lead

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True


def call_request(**content):
    return SimpleNamespace(
        id=1, organization_id=7, lead_id=11, status="approved",
        channel="automated_call", provider="bland", contact="+13055551212",
        compliance_decision_id=5, content=content, provider_reference=None,
        provider_status=None, provider_response={}, dispatched_by_user_id=None,
        dispatched_at=None, error=None, requested_by_user_id=3,
    )


def dispatch(db, monkeypatch, dialled):
    """Run the endpoint with surrounding approval/compliance checks stubbed."""
    monkeypatch.setattr(og, "_approved", lambda *a, **k: True)
    monkeypatch.setattr(og, "_decision_for_request", lambda *a, **k: SimpleNamespace(id=5))
    monkeypatch.setattr(og, "_active_suppression", lambda *a, **k: None)

    async def _fake_bland_call(request):
        dialled.append(request)
        return {"provider_reference": "call_1", "provider_status": "queued", "provider_response": {}}

    monkeypatch.setattr(og, "_dispatch_bland_call", _fake_bland_call)
    return asyncio.run(og.dispatch_outbound_request(1, principal(), db))


def test_a_call_that_hides_the_machine_is_never_dialled(monkeypatch):
    db = DispatchDb(
        call_request(first_sentence="Hi, this is Alex calling about your property."),
        SimpleNamespace(state="GA", seller_name="R. Diaz"),
    )
    dialled = []
    with pytest.raises(HTTPException) as raised:
        dispatch(db, monkeypatch, dialled)
    assert raised.value.status_code == 422
    assert "opening_line_does_not_disclose_automated_system" in str(raised.value.detail)
    assert dialled == []


def test_a_disclosed_call_goes_through(monkeypatch):
    db = DispatchDb(
        call_request(first_sentence="Hi, this is an automated call from SAHJONY Capital."),
        SimpleNamespace(state="GA", seller_name="R. Diaz"),
    )
    dialled = []
    result = dispatch(db, monkeypatch, dialled)
    assert result["status"] == "queued"
    assert len(dialled) == 1


def test_the_disclosure_may_live_in_the_task_prompt(monkeypatch):
    db = DispatchDb(
        call_request(task="You are an automated assistant asking about the property."),
        SimpleNamespace(state="GA", seller_name="R. Diaz"),
    )
    dialled = []
    assert dispatch(db, monkeypatch, dialled)["status"] == "queued"
    assert len(dialled) == 1


def test_a_dispatched_call_is_written_to_the_call_log(monkeypatch):
    from app.voice_models import VoiceCall

    db = DispatchDb(
        call_request(first_sentence="Hi, this is an automated call from SAHJONY Capital."),
        SimpleNamespace(state="FL", seller_name="R. Diaz"),
    )
    dispatch(db, monkeypatch, [])
    calls = [row for row in db.added if isinstance(row, VoiceCall)]
    assert len(calls) == 1
    assert calls[0].direction == "outbound"
    assert calls[0].ai_disclosed is True
    assert calls[0].state == "FL"
    assert calls[0].recorded is False


def test_recording_in_an_all_party_state_needs_the_script_to_say_so(monkeypatch):
    db = DispatchDb(
        call_request(
            first_sentence="Hi, this is an automated call from SAHJONY Capital.",
            record=True,
        ),
        SimpleNamespace(state="FL", seller_name="R. Diaz"),
    )
    dialled = []
    with pytest.raises(HTTPException) as raised:
        dispatch(db, monkeypatch, dialled)
    assert "recording" in str(raised.value.detail)
    assert dialled == []


def test_sms_is_not_subjected_to_the_call_script_gate(monkeypatch):
    request = call_request(body="Hi Rosa, it's Sam with SAHJONY. Reply STOP to opt out.")
    request.channel, request.provider = "sms", "bland"
    db = DispatchDb(request, SimpleNamespace(state="GA", seller_name="R. Diaz"))

    async def _fake_bland_sms(_request):
        return {
            "provider_reference": "conv_1",
            "provider_status": "queued",
            "provider_response": {"conversation_id": "conv_1", "workflow_id": "wf_1"},
        }

    monkeypatch.setattr(og, "_dispatch_bland_sms", _fake_bland_sms)
    monkeypatch.setattr(og, "_approved", lambda *a, **k: True)
    monkeypatch.setattr(og, "_decision_for_request", lambda *a, **k: SimpleNamespace(id=5))
    monkeypatch.setattr(og, "_active_suppression", lambda *a, **k: None)
    assert asyncio.run(og.dispatch_outbound_request(1, principal(), db))["status"] == "queued"

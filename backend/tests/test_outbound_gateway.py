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
    _validate_channel_provider("sms", "twilio")
    _validate_channel_provider("automated_call", "bland")
    with pytest.raises(HTTPException):
        _validate_channel_provider("sms", "bland")


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
    # Exactly what a number copied out of a chat window looks like. Vercel
    # stores an environment variable as pasted, so the smart quotes survive
    # into production and the provider rejects every call with an error that
    # never mentions quoting.
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
    # Setting both is not setting two things. Bland's API has one `from`
    # field, so the second value is never sent anywhere.
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    monkeypatch.setenv("BLAND_DEFAULT_CALLER_ID", "+12164804413")
    assert og.caller_id() == "+13465214387"


def test_no_configured_caller_id_is_not_an_error(monkeypatch):
    # Bland can place calls from a number on the account, so an unset caller
    # ID is a valid configuration rather than a failure.
    monkeypatch.delenv("BLAND_DEFAULT_FROM_NUMBER", raising=False)
    monkeypatch.delenv("BLAND_DEFAULT_CALLER_ID", raising=False)
    assert og.caller_id() is None


def test_the_voice_number_is_never_used_as_an_sms_sender(monkeypatch):
    # A Bland voice number is not registered for A2P 10DLC. Sending texts from
    # it gets the traffic rejected or fined, and neither failure points back
    # at this configuration. With a voice number but no Twilio sender, the
    # send must fail rather than quietly borrow the voice number.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC-test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)

    request = call_request(body="Hi, it's Sam with SAHJONY. Reply STOP to opt out.")
    request.channel, request.provider = "sms", "twilio"
    with pytest.raises(HTTPException) as raised:
        asyncio.run(og._dispatch_twilio(request))
    assert raised.value.status_code == 503
    assert "sender" in str(raised.value.detail).lower()


# ------------------------------------------- the AI-disclosure gate on calls --

class DispatchDb:
    """Just enough database to drive the dispatch endpoint.

    ``get`` dispatches on the model, because the endpoint looks up both the
    outbound request and the lead through the same handle.
    """

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
    )


def dispatch(db, monkeypatch, dialled):
    """Run the endpoint with the surrounding checks satisfied.

    Approval, the compliance decision and suppression are all stubbed to pass,
    so whatever the endpoint does next is attributable to the script gate alone.
    """
    monkeypatch.setattr(og, "_approved", lambda *a, **k: True)
    monkeypatch.setattr(og, "_decision_for_request", lambda *a, **k: SimpleNamespace(id=5))
    monkeypatch.setattr(og, "_active_suppression", lambda *a, **k: None)

    async def _fake_bland(request):
        dialled.append(request)
        return {"provider_reference": "call_1", "provider_status": "queued", "provider_response": {}}

    monkeypatch.setattr(og, "_dispatch_bland", _fake_bland)
    return asyncio.run(og.dispatch_outbound_request(1, principal(), db))


def test_a_call_that_hides_the_machine_is_never_dialled(monkeypatch):
    # The point of the gate. Preflight is advisory, so if the dispatcher does
    # not enforce this, an undisclosed AI voice reaches a real phone.
    db = DispatchDb(
        call_request(first_sentence="Hi, this is Alex calling about your property."),
        SimpleNamespace(state="GA", seller_name="R. Diaz"),
    )
    dialled = []
    with pytest.raises(HTTPException) as raised:
        dispatch(db, monkeypatch, dialled)
    assert raised.value.status_code == 422
    assert "opening_line_does_not_disclose_automated_system" in str(raised.value.detail)
    assert dialled == [], "the call must be refused before the provider is reached"


def test_a_disclosed_call_goes_through(monkeypatch):
    # The gate has to be capable of allowing, or it is not a gate.
    db = DispatchDb(
        call_request(first_sentence="Hi, this is an automated call from SAHJONY Capital."),
        SimpleNamespace(state="GA", seller_name="R. Diaz"),
    )
    dialled = []
    result = dispatch(db, monkeypatch, dialled)
    assert result["status"] == "queued"
    assert len(dialled) == 1


def test_the_disclosure_may_live_in_the_task_prompt(monkeypatch):
    # With no first_sentence, Bland improvises the opening from the task, so a
    # disclosure instructed there is a real disclosure.
    db = DispatchDb(
        call_request(task="You are an automated assistant asking about the property."),
        SimpleNamespace(state="GA", seller_name="R. Diaz"),
    )
    dialled = []
    assert dispatch(db, monkeypatch, dialled)["status"] == "queued"
    assert len(dialled) == 1


def test_a_dispatched_call_is_written_to_the_call_log(monkeypatch):
    # Same failure the SMS log had: a channel that sends but never records the
    # send leaves nothing to audit and nothing for a cap to count.
    from app.voice_models import VoiceCall

    db = DispatchDb(
        call_request(first_sentence="Hi, this is an automated call from SAHJONY Capital."),
        SimpleNamespace(state="FL", seller_name="R. Diaz"),
    )
    dispatch(db, monkeypatch, [])
    calls = [row for row in db.added if isinstance(row, VoiceCall)]
    assert len(calls) == 1, "dispatch must log the call"
    assert calls[0].direction == "outbound"
    assert calls[0].ai_disclosed is True
    assert calls[0].state == "FL"
    assert calls[0].recorded is False


def test_recording_in_an_all_party_state_needs_the_script_to_say_so(monkeypatch):
    # Recording is not configurable today, but the gate is standing so it does
    # not have to be remembered if it ever becomes so.
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
    # A text has no opening line to disclose. Applying the voice rule here
    # would block every message.
    request = call_request(body="Hi Rosa, it's Sam with SAHJONY. Reply STOP to opt out.")
    request.channel, request.provider = "sms", "twilio"
    db = DispatchDb(request, SimpleNamespace(state="GA", seller_name="R. Diaz"))

    async def _fake_twilio(_request):
        return {"provider_reference": "sm_1", "provider_status": "queued", "provider_response": {}}

    monkeypatch.setattr(og, "_dispatch_twilio", _fake_twilio)
    assert dispatch(db, monkeypatch, [])["status"] == "queued"

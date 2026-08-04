"""Bland.ai call rules.

Voice carries two exposures messaging does not. An AI voice is an artificial
voice under the FCC's 2024 ruling, and recording a call without every party's
consent is a criminal statute in roughly a dozen states rather than a
compliance ticket.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")
os.environ.setdefault("BLAND_AI_API_KEY", "test-key")

from app import voice_engine as ve


# ------------------------------------------------------ recording consent --

def test_an_unknown_state_is_treated_as_all_party():
    # Fail closed. A missing state is missing information, and assuming the
    # permissive rule is the only direction with criminal exposure.
    assert ve.requires_all_party_consent(None) is True
    assert ve.requires_all_party_consent("") is True
    assert ve.requires_all_party_consent("   ") is True


def test_florida_requires_all_party_consent():
    # The first configured market is Escambia County, Florida.
    assert ve.requires_all_party_consent("FL") is True
    assert ve.requires_all_party_consent("fl") is True


def test_known_all_party_states_are_covered():
    for state in ("CA", "IL", "MA", "MD", "PA", "WA", "MT", "NH", "OR", "DE"):
        assert ve.requires_all_party_consent(state) is True, state


def test_contested_states_are_treated_as_all_party():
    # Sources disagree on these. Over-disclosing costs a sentence of script.
    for state in ("CT", "MI", "NV"):
        assert ve.requires_all_party_consent(state) is True, state


def test_one_party_states_are_not_over_reported():
    # The guard has to be capable of saying no, or it is not a distinction.
    for state in ("NY", "TX", "GA", "OH", "AZ", "CO"):
        assert ve.requires_all_party_consent(state) is False, state


# --------------------------------------------------------- AI disclosure --

def test_a_script_that_hides_the_machine_is_refused():
    problems = ve.validate_call_script(
        "Hi, this is Alex calling about your property.", "GA", record=False
    )
    assert "opening_line_does_not_disclose_automated_system" in problems


def test_common_ways_of_disclosing_are_accepted():
    for line in (
        "Hi, this is an automated call from SAHJONY Capital.",
        "You're speaking with an AI assistant.",
        "This is a virtual assistant calling on behalf of SAHJONY.",
        "I'm an automated system calling about your property.",
    ):
        assert ve.discloses_ai(line), line


def test_the_indefinite_article_is_not_mistaken_for_ai():
    # "a" must not satisfy the AI pattern, or every script passes.
    assert not ve.discloses_ai("I have a interest in your property")
    assert not ve.discloses_ai("Hi, I am a person calling about your house")


def test_an_empty_script_is_refused_outright():
    assert ve.validate_call_script("", "GA", record=False) == ["missing_opening_line"]


# ------------------------------------------------ recording gate on script --

def test_recording_without_disclosure_is_refused_in_an_all_party_state():
    problems = ve.validate_call_script(
        "Hi, this is an automated call from SAHJONY Capital.", "FL", record=True
    )
    assert "opening_line_does_not_disclose_recording" in problems
    assert any("all_party_consent_state_requires" in p for p in problems)


def test_recording_with_disclosure_passes_in_an_all_party_state():
    assert ve.validate_call_script(
        "Hi, this is an automated call from SAHJONY Capital. This call is recorded.",
        "FL", record=True,
    ) == []


def test_not_recording_needs_no_recording_disclosure():
    assert ve.validate_call_script(
        "Hi, this is an automated call from SAHJONY Capital.", "FL", record=False
    ) == []


def test_a_missing_api_key_blocks_every_call(monkeypatch):
    monkeypatch.delenv("BLAND_AI_API_KEY", raising=False)
    problems = ve.validate_call_script(
        "Hi, this is an automated call from SAHJONY Capital.", "GA", record=False
    )
    assert "bland_api_key_not_configured" in problems


# ----------------------------------------------------------- verbal opt-out --

def test_a_spoken_do_not_call_request_is_recognised():
    for line in (
        "please take me off your list",
        "remove me from your calls",
        "do not call me again",
        "don't call this number",
        "stop calling me",
        "never call here again",
        "quit calling",
        "opt me out",
    ):
        assert ve.detect_verbal_opt_out(line), line


def test_the_request_is_found_inside_a_longer_transcript():
    transcript = (
        "Agent: Hi, this is an automated call about your property. "
        "Homeowner: I'm not selling, please take me off your list. "
        "Agent: Understood, thank you."
    )
    assert ve.detect_verbal_opt_out(transcript)


def test_ordinary_disinterest_is_not_a_do_not_call_request():
    # "Not interested" declines this offer. Treating it as a permanent DNC
    # would silently discard leads who might sell later.
    assert not ve.detect_verbal_opt_out("I'm not interested right now")
    assert not ve.detect_verbal_opt_out("what price were you thinking?")
    assert not ve.detect_verbal_opt_out("")


def test_asking_never_to_be_called_again_is_a_request():
    assert ve.detect_verbal_opt_out("I'm not interested, don't call again")


# ------------------------------------------------------------ integration --

def test_recording_stays_off_by_default_in_the_dispatcher():
    # The dispatcher hardcodes record: False. If that ever becomes opt-out
    # rather than opt-in, every call in an all-party state is exposed.
    source = open("app/outbound_gateway.py").read()
    assert '"record": False' in source


def test_quiet_hours_still_cover_both_call_channels():
    from app.compliance import QUIET_HOURS_CHANNELS

    assert "live_call" in QUIET_HOURS_CHANNELS
    assert "automated_call" in QUIET_HOURS_CHANNELS


# ------------------------------------------------- inbound number and callbacks --

def test_the_inbound_numbers_are_validated(monkeypatch):
    import pytest as _pytest
    from fastapi import HTTPException

    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+12164804413")
    assert ve.inbound_numbers() == ("+12164804413",)

    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "“+12164804413”")
    with _pytest.raises(HTTPException):
        ve.inbound_numbers()


def test_several_inbound_lines_can_be_configured(monkeypatch):
    # Both numbers on the Bland account answer, which is the setup that makes
    # the callback rule satisfiable without giving either up.
    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+13465214387, +12164804413")
    assert ve.inbound_numbers() == ("+13465214387", "+12164804413")


def test_one_bad_number_in_the_list_fails_the_whole_list(monkeypatch):
    # Silently dropping the invalid one would leave a line nobody notices is
    # unmonitored.
    import pytest as _pytest
    from fastapi import HTTPException

    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+13465214387,216-480-4413")
    with _pytest.raises(HTTPException):
        ve.inbound_numbers()


def test_an_unset_inbound_number_is_not_an_error(monkeypatch):
    monkeypatch.delenv("BLAND_INBOUND_NUMBER", raising=False)
    assert ve.inbound_numbers() == ()


def test_the_inbound_line_is_not_read_from_the_outbound_caller_id(monkeypatch):
    # BLAND_DEFAULT_CALLER_ID is an outbound name. If the inbound number were
    # read from it, a typo in BLAND_DEFAULT_FROM_NUMBER would start placing
    # outbound calls from the inbound line.
    monkeypatch.delenv("BLAND_INBOUND_NUMBER", raising=False)
    monkeypatch.setenv("BLAND_DEFAULT_CALLER_ID", "+12164804413")
    assert ve.inbound_numbers() == ()


def test_a_caller_id_with_no_agent_behind_it_is_reported(monkeypatch):
    # Outbound from Houston, agent answering only in Cleveland.
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+12164804413")
    result = ve.callback_reachability()
    assert result["callback_reaches_inbound_agent"] is False
    assert "64.1601" in result["note"]


def test_a_caller_id_among_the_answered_lines_is_reachable(monkeypatch):
    # The fix that keeps both numbers: give the caller ID an agent too.
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+13465214387,+12164804413")
    result = ve.callback_reachability()
    assert result["callback_reaches_inbound_agent"] is True
    assert result["inbound_numbers"] == ["+13465214387", "+12164804413"]


def test_matching_numbers_are_reported_as_reachable(monkeypatch):
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+12164804413")
    monkeypatch.setenv("BLAND_INBOUND_NUMBER", "+12164804413")
    assert ve.callback_reachability()["callback_reaches_inbound_agent"] is True


def test_reachability_is_unknown_when_a_number_is_missing(monkeypatch):
    # Unknown, not fine. Reporting False would be a false alarm and reporting
    # True would be a guess.
    monkeypatch.delenv("BLAND_INBOUND_NUMBER", raising=False)
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    assert ve.callback_reachability()["callback_reaches_inbound_agent"] is None


# ------------------------------------------------------ webhook signatures --

import base64
import hashlib
import hmac
import json


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_a_correctly_signed_delivery_verifies(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    body = b'{"call_id":"abc"}'
    ok, detail = ve.verify_webhook_signature({"x-webhook-signature": sign("s3cret", body)}, body)
    assert ok is True
    assert detail == "x-webhook-signature"


def test_a_forged_signature_is_refused(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    body = b'{"call_id":"abc"}'
    ok, detail = ve.verify_webhook_signature({"x-webhook-signature": sign("wrong-key", body)}, body)
    assert ok is False
    assert detail == "signature_mismatch"


def test_a_tampered_body_no_longer_matches(monkeypatch):
    # The whole point. A signature over different bytes must not carry over.
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    signature = sign("s3cret", b'{"transcript":"hello"}')
    ok, _ = ve.verify_webhook_signature(
        {"x-webhook-signature": signature}, b'{"transcript":"take me off your list"}'
    )
    assert ok is False


def test_an_unsigned_delivery_is_refused(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    ok, detail = ve.verify_webhook_signature({}, b"{}")
    assert ok is False
    assert detail == "no_signature_header"


def test_a_missing_secret_rejects_everything(monkeypatch):
    # Fail closed. Accepting anything when unconfigured would look healthy
    # while leaving the endpoint open to the whole internet.
    monkeypatch.delenv("BLAND_AI_WEBHOOK_SECRET", raising=False)
    body = b"{}"
    ok, detail = ve.verify_webhook_signature({"x-webhook-signature": sign("", body)}, body)
    assert ok is False
    assert detail == "webhook_secret_not_configured"


def test_an_empty_secret_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "   ")
    ok, detail = ve.verify_webhook_signature({"x-webhook-signature": "anything"}, b"{}")
    assert ok is False
    assert detail == "webhook_secret_not_configured"


def test_base64_encoding_of_the_same_digest_is_accepted(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    body = b'{"call_id":"abc"}'
    encoded = base64.b64encode(
        hmac.new(b"s3cret", body, hashlib.sha256).digest()
    ).decode()
    ok, _ = ve.verify_webhook_signature({"x-webhook-signature": encoded}, body)
    assert ok is True


def test_a_sha256_prefix_is_unwrapped(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    body = b'{"call_id":"abc"}'
    ok, _ = ve.verify_webhook_signature(
        {"x-webhook-signature": f"sha256={sign('s3cret', body)}"}, body
    )
    assert ok is True


def test_the_header_name_can_be_pinned(monkeypatch):
    # Once Bland's real header name is known, pinning it stops the others
    # being accepted at all.
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SIGNATURE_HEADER", "x-bland-signature")
    body = b"{}"
    signature = sign("s3cret", body)
    assert ve.verify_webhook_signature({"x-bland-signature": signature}, body)[0] is True
    assert ve.verify_webhook_signature({"x-webhook-signature": signature}, body)[0] is False


def test_every_candidate_header_is_tried_by_default(monkeypatch):
    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    monkeypatch.delenv("BLAND_AI_WEBHOOK_SIGNATURE_HEADER", raising=False)
    body = b"{}"
    for name in ve.SIGNATURE_HEADER_CANDIDATES:
        assert ve.verify_webhook_signature({name: sign("s3cret", body)}, body)[0] is True, name


def test_signature_comparison_is_constant_time():
    # A plain == leaks the correct prefix through timing. Assert the call is
    # the library one rather than trying to time it in a test.
    import inspect

    source = inspect.getsource(ve.verify_webhook_signature)
    assert "compare_digest" in source
    assert "presented == expected" not in source


def test_the_webhook_reads_raw_bytes_not_a_parsed_body():
    # Re-encoding a parsed body changes key order and whitespace, so the
    # signature would never match. This is easy to "clean up" and break.
    import inspect

    source = inspect.getsource(ve.bland_webhook)
    assert "await request.body()" in source
    assert source.index("verify_webhook_signature") < source.index("request.json()"), (
        "the signature must be checked before the body is parsed"
    )


# -------------------------------------------------- webhook, end to end --

import pytest


@pytest.fixture
def webhook_client(monkeypatch):
    """The webhook mounted on its own app, over the real database."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import SessionLocal, get_db

    monkeypatch.setenv("BLAND_AI_WEBHOOK_SECRET", "s3cret")
    monkeypatch.delenv("BLAND_AI_WEBHOOK_SIGNATURE_HEADER", raising=False)
    monkeypatch.setenv("BLAND_INBOUND_ORGANIZATION_ID", "424242")

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(ve.router)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _voice_rows(organization_id=424242):
    from app.database import SessionLocal
    from app.voice_models import VoiceCall

    db = SessionLocal()
    try:
        return db.query(VoiceCall).filter(VoiceCall.organization_id == organization_id).all()
    finally:
        db.close()


def _cleanup(organization_id=424242):
    from app.compliance_models import ContactSuppression
    from app.database import SessionLocal
    from app.voice_models import VoiceCall

    db = SessionLocal()
    try:
        db.query(VoiceCall).filter(VoiceCall.organization_id == organization_id).delete()
        db.query(ContactSuppression).filter(
            ContactSuppression.organization_id == organization_id
        ).delete()
        db.commit()
    finally:
        db.close()


def test_an_unsigned_post_is_rejected_and_writes_nothing(webhook_client):
    # The endpoint is public. If this ever returns 200, anyone on the internet
    # can write calls and opt-outs into the workspace.
    _cleanup()
    try:
        body = json.dumps({"from": "+13055551212", "call_id": "unsigned-1"})
        response = webhook_client.post(
            "/voice/webhooks/bland", content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401
        assert _voice_rows() == [], "a rejected delivery must not be recorded"
    finally:
        _cleanup()


def test_a_signed_delivery_is_recorded(webhook_client):
    _cleanup()
    try:
        body = json.dumps({"from": "+13055551212", "call_id": "signed-1", "transcript": "hi"})
        response = webhook_client.post(
            "/voice/webhooks/bland", content=body,
            headers={
                "Content-Type": "application/json",
                "x-webhook-signature": sign("s3cret", body.encode()),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["accepted"] is True
        rows = _voice_rows()
        assert len(rows) == 1
        assert rows[0].provider_call_id == "signed-1"
    finally:
        _cleanup()


def test_a_spoken_opt_out_arriving_by_webhook_suppresses_the_number(webhook_client):
    # The reason the webhook exists at all: a do-not-call request that arrives
    # while nobody is logged in still has to be honoured.
    from app.compliance_models import ContactSuppression
    from app.database import SessionLocal

    _cleanup()
    try:
        body = json.dumps({
            "from": "+13055559999", "call_id": "optout-1",
            "transcript": "I'm not selling, please take me off your list",
        })
        response = webhook_client.post(
            "/voice/webhooks/bland", content=body,
            headers={
                "Content-Type": "application/json",
                "x-webhook-signature": sign("s3cret", body.encode()),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["verbal_opt_out"] is True

        db = SessionLocal()
        try:
            channels = {
                row.channel for row in db.query(ContactSuppression).filter(
                    ContactSuppression.organization_id == 424242,
                    ContactSuppression.contact == "+13055559999",
                    ContactSuppression.active.is_(True),
                ).all()
            }
        finally:
            db.close()
        assert {"live_call", "automated_call", "sms"} <= channels, channels
    finally:
        _cleanup()


def test_a_redelivered_call_is_not_recorded_twice(webhook_client):
    # Providers retry. Two rows for one call would double-count everything
    # downstream and duplicate the activity feed.
    _cleanup()
    try:
        body = json.dumps({"from": "+13055551212", "call_id": "retry-1"})
        headers = {
            "Content-Type": "application/json",
            "x-webhook-signature": sign("s3cret", body.encode()),
        }
        first = webhook_client.post("/voice/webhooks/bland", content=body, headers=headers)
        second = webhook_client.post("/voice/webhooks/bland", content=body, headers=headers)
        assert first.status_code == second.status_code == 200
        assert second.json()["duplicate"] is True
        assert len(_voice_rows()) == 1
    finally:
        _cleanup()


def test_an_unattributable_call_is_refused_rather_than_guessed(webhook_client, monkeypatch):
    # Filing one tenant's call under another is worse than losing the delivery,
    # and a 4xx keeps it in Bland's retry log instead of vanishing.
    monkeypatch.delenv("BLAND_INBOUND_ORGANIZATION_ID", raising=False)
    _cleanup()
    try:
        body = json.dumps({"from": "+13055551212", "call_id": "orphan-1"})
        response = webhook_client.post(
            "/voice/webhooks/bland", content=body,
            headers={
                "Content-Type": "application/json",
                "x-webhook-signature": sign("s3cret", body.encode()),
            },
        )
        assert response.status_code == 422
        assert _voice_rows() == []
    finally:
        _cleanup()


def test_the_rejection_names_the_headers_it_saw(webhook_client):
    # The one thing that cannot be determined from here is which header Bland
    # sends. The first real delivery should answer it.
    body = json.dumps({"from": "+13055551212"})
    response = webhook_client.post(
        "/voice/webhooks/bland", content=body,
        headers={"Content-Type": "application/json", "x-mystery-signature": "abc"},
    )
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert "x-mystery-signature" in detail["received_headers"]
    assert "x-webhook-signature" in detail["looked_for"]


def test_the_documented_api_key_is_the_one_the_code_reads():
    # These had drifted: .env.example and the setup checklist both said
    # BLAND_API_KEY while every call site read BLAND_AI_API_KEY. Configuring
    # from the example produced a setup that looked complete and 503'd on the
    # first call, which is the worst version of a misconfiguration -- it fails
    # in production rather than at setup.
    import pathlib

    from app.getting_started import CREDENTIAL_ENVS

    assert CREDENTIAL_ENVS["Seller communications"] == "BLAND_AI_API_KEY"

    example = pathlib.Path(__file__).resolve().parents[2] / ".env.example"
    declared = {
        line.split("=", 1)[0].strip()
        for line in example.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert "BLAND_AI_API_KEY" in declared, ".env.example must document the name that is read"
    assert "BLAND_API_KEY" not in declared, "the unread short name invites a dead configuration"

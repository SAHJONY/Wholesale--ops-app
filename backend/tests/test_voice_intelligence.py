from types import SimpleNamespace

from app.voice_intelligence import call_qa, jurisdiction_policy


def test_unknown_state_fails_closed_for_recording():
    policy = jurisdiction_policy(None)
    assert policy["state_known"] is False
    assert policy["all_party_consent_treated_as_required"] is True
    assert policy["recording_default"] is False
    assert policy["fail_closed_reason"] == "state_unknown"


def test_florida_is_treated_as_all_party():
    policy = jurisdiction_policy("FL", "inbound")
    assert policy["state"] == "FL"
    assert policy["all_party_consent_treated_as_required"] is True
    assert policy["autonomous_outbound_dispatch"] is False


def test_qa_penalizes_missing_disclosure_and_transcript():
    call = SimpleNamespace(
        id=1,
        ai_disclosed=False,
        transcript_excerpt=None,
        recorded=False,
        recording_consent_basis=None,
        verbal_opt_out=False,
        evidence={},
    )
    result = call_qa(call)
    assert result["needs_review"] is True
    assert "ai_disclosure_not_recorded" in result["blockers"]
    assert "missing_transcript" in result["blockers"]
    assert result["score"] < 80


def test_qa_rewards_disclosure_transcript_qualification_and_four_pillars():
    call = SimpleNamespace(
        id=2,
        ai_disclosed=True,
        transcript_excerpt="Seller discussed the property and timeline.",
        recorded=False,
        recording_consent_basis=None,
        verbal_opt_out=False,
        evidence={"phone_qualification": {
            "motivation": "Inherited property",
            "timeline_days": 20,
            "condition": "Needs roof and HVAC",
            "seller_price": 120000,
        }},
    )
    result = call_qa(call)
    assert result["pillars_captured"] == 4
    assert result["score"] == 100.0
    assert result["grade"] == "A"
    assert result["needs_review"] is False


def test_recorded_call_without_consent_basis_is_a_blocker():
    call = SimpleNamespace(
        id=3,
        ai_disclosed=True,
        transcript_excerpt="Transcript present",
        recorded=True,
        recording_consent_basis=None,
        verbal_opt_out=False,
        evidence={"phone_qualification": {}},
    )
    result = call_qa(call)
    assert "recording_without_recorded_consent_basis" in result["blockers"]
    assert result["needs_review"] is True

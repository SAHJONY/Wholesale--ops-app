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

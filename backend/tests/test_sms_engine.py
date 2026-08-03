"""SMS compliance rules.

Every assertion here corresponds to something that costs money when wrong:
statutory damages per message, a carrier filtering the sender, or a homeowner
being texted after asking not to be.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")
os.environ.setdefault("SMS_BUSINESS_NAME", "SAHJONY Capital")

from app import sms_engine as se
from app.compliance import QUIET_HOURS_CHANNELS


# ------------------------------------------------------------- quiet hours --

def test_quiet_hours_apply_to_sms():
    # They did not. The restriction covers texts exactly as it covers calls,
    # and a 3am message is a per-message violation whether it rang or buzzed.
    assert "sms" in QUIET_HOURS_CHANNELS
    assert "automated_call" in QUIET_HOURS_CHANNELS
    assert "live_call" in QUIET_HOURS_CHANNELS


def test_email_is_not_subject_to_quiet_hours():
    assert "email" not in QUIET_HOURS_CHANNELS


# ----------------------------------------------------------- opt-out intent --

def test_bare_stop_is_an_opt_out():
    assert se.classify_inbound("STOP")[0] == "opt_out"
    assert se.classify_inbound("stop")[0] == "opt_out"


def test_punctuation_and_whitespace_do_not_defeat_opt_out():
    for body in ("STOP.", "  stop  ", "Stop!", "STOP,"):
        assert se.classify_inbound(body)[0] == "opt_out", body


def test_opt_out_survives_a_trailing_word():
    # "stop please" is unambiguous to a person and must be to the system.
    assert se.classify_inbound("stop please")[0] == "opt_out"
    assert se.classify_inbound("STOP texting me")[0] == "opt_out"


def test_every_conventional_opt_out_keyword_is_recognised():
    for word in ("stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke"):
        assert se.classify_inbound(word)[0] == "opt_out", word


def test_a_keyword_buried_mid_sentence_is_not_a_command():
    # Left for a human rather than guessed at in either direction.
    assert se.classify_inbound("please don't stop sending me offers")[0] is None
    assert se.classify_inbound("I want to end up selling by June")[0] is None


def test_help_and_opt_in_are_distinguished_from_opt_out():
    assert se.classify_inbound("HELP")[0] == "help"
    assert se.classify_inbound("START")[0] == "opt_in"
    assert se.classify_inbound("yes")[0] == "opt_in"


def test_an_ordinary_reply_is_not_a_keyword():
    assert se.classify_inbound("How much are you offering?")[0] is None
    assert se.classify_inbound("")[0] is None


# ---------------------------------------------------------- content gating --

def test_a_body_without_opt_out_instructions_cannot_be_sent():
    problems = se.validate_body("Hi, this is SAHJONY Capital. Want to sell?")
    assert "missing_opt_out_instruction" in problems


def test_a_body_that_does_not_identify_the_sender_cannot_be_sent():
    problems = se.validate_body("Hi, want to sell your house? Reply STOP to opt out.")
    assert "missing_sender_identification" in problems


def test_a_compliant_body_passes():
    assert se.validate_body(
        "Hi Dana, this is Alex with SAHJONY Capital. Open to an offer? Reply STOP to opt out."
    ) == []


def test_an_empty_body_is_rejected():
    assert se.validate_body("   ") == ["empty_body"]


def test_an_overlong_body_is_rejected():
    long_body = "SAHJONY Capital " + ("x" * 400) + " Reply STOP to opt out."
    assert "body_exceeds_two_segments" in se.validate_body(long_body)


def test_missing_business_name_configuration_blocks_every_send(monkeypatch):
    # Failing closed: without a configured sender name no message can identify
    # who is texting, so none may go out.
    monkeypatch.delenv("SMS_BUSINESS_NAME", raising=False)
    problems = se.validate_body("Hi, this is someone. Reply STOP to opt out.")
    assert "sms_business_name_not_configured" in problems


# ------------------------------------------------------------ drafted copy --

def test_every_template_produces_a_sendable_body():
    for trigger in se.TEMPLATES:
        result = se.draft_message(trigger, "Dana Reed", "12 Oak St", "Pensacola", "Alex")
        assert result["sendable"], (trigger, result["blockers"])


def test_probate_copy_never_mentions_the_death_or_the_case():
    body = se.draft_message("probate", "Dana", "12 Oak St", "Pensacola", "Alex")["body"].lower()
    for word in ("probate", "estate", "deceased", "passed away", "inherit"):
        assert word not in body, word


def test_foreclosure_copy_never_mentions_the_filing():
    body = se.draft_message("lis_pendens", "Dana", "12 Oak St", "Pensacola", "Alex")["body"].lower()
    for word in ("foreclos", "lis pendens", "default", "auction", "lawsuit"):
        assert word not in body, word


def test_an_unknown_trigger_falls_back_to_general_rather_than_failing():
    result = se.draft_message("nonsense_trigger", "Dana", "12 Oak St", "Pensacola", "Alex")
    assert result["trigger"] == "general"
    assert result["sendable"]


def test_a_missing_first_name_does_not_produce_a_broken_greeting():
    body = se.draft_message("general", "", "12 Oak St", "Pensacola", "Alex")["body"]
    assert "Hi there," in body


def test_only_the_first_name_is_used():
    body = se.draft_message("general", "Dana Reed Junior", "12 Oak St", "Pensacola", "Alex")["body"]
    assert "Hi Dana," in body
    assert "Reed" not in body


def test_drafts_stay_within_two_segments():
    for trigger in se.TEMPLATES:
        result = se.draft_message(
            trigger, "Bartholomew", "1234 Extraordinarily Long Boulevard", "Pensacola", "Alexandra"
        )
        assert result["characters"] <= se.SEGMENT_LIMIT, trigger


# ------------------------------------------------------------- frequency ---

def test_frequency_cap_is_a_small_number():
    # A cap that permits daily contact is not a cap.
    assert se.MAX_MESSAGES_PER_WINDOW <= 5
    assert se.FREQUENCY_WINDOW_DAYS >= 7


# ------------------------------------------------- the cap must actually bite --

def test_the_frequency_cap_counts_real_sends(tmp_path):
    """A cap nothing feeds is not a cap.

    recent_message_count reads outbound rows from the send log. When this was
    first written nothing anywhere created one, so the count was always zero and
    the limit could never fire. The check looked present and did nothing.
    """
    from datetime import datetime, timezone

    from app.database import SessionLocal
    from app.sms_models import SmsMessage

    db = SessionLocal()
    contact = "+15550001111"
    org = 987654
    now = datetime.now(timezone.utc)
    try:
        assert se.recent_message_count(db, org, contact, now) == 0
        for i in range(se.MAX_MESSAGES_PER_WINDOW):
            db.add(SmsMessage(
                organization_id=org, direction="outbound", contact=contact,
                body=f"message {i}", status="queued",
            ))
        db.commit()

        count = se.recent_message_count(db, org, contact, now)
        assert count == se.MAX_MESSAGES_PER_WINDOW
        assert count >= se.MAX_MESSAGES_PER_WINDOW, "cap should now be reached"

        # Inbound replies are not sends and must not consume the allowance.
        db.add(SmsMessage(
            organization_id=org, direction="inbound", contact=contact,
            body="how much?", status="received",
        ))
        db.commit()
        assert se.recent_message_count(db, org, contact, now) == se.MAX_MESSAGES_PER_WINDOW
    finally:
        db.query(SmsMessage).filter(SmsMessage.organization_id == org).delete()
        db.commit()
        db.close()


def test_the_dispatch_path_writes_a_send_row():
    # The gap was structural: the cap read a log nothing wrote to. Assert the
    # dispatcher is the thing that writes it, so the two cannot drift apart.
    source = open("app/outbound_gateway.py").read()
    assert "SmsMessage(" in source, "outbound dispatch must log sends"
    assert 'direction="outbound"' in source

from datetime import datetime, timezone

from app.sms_scheduling import MAX_DUE_BATCH, parse_agent_datetime, resolve_seller_time


NOW = datetime(2026, 8, 7, 16, 0, tzinfo=timezone.utc)


def test_agent_datetime_requires_timezone():
    assert parse_agent_datetime("2026-08-08T15:00:00") is None
    assert parse_agent_datetime("2026-08-08T15:00:00-04:00") == datetime(2026, 8, 8, 19, 0, tzinfo=timezone.utc)


def test_tomorrow_callback_is_resolved_in_recipient_timezone():
    value, confidence, source = resolve_seller_time("Call me tomorrow at 3pm", "America/New_York", NOW)
    assert value == datetime(2026, 8, 8, 19, 0, tzinfo=timezone.utc)
    assert confidence >= 90
    assert source == "relative_tomorrow"


def test_weekday_callback_is_future_and_explicit():
    value, confidence, source = resolve_seller_time("Monday at 2:30 pm works", "America/New_York", NOW)
    assert value == datetime(2026, 8, 10, 18, 30, tzinfo=timezone.utc)
    assert confidence >= 90
    assert source == "explicit_weekday"


def test_explicit_calendar_date_has_high_confidence():
    value, confidence, source = resolve_seller_time("8/20/2026 at 10:30am", "America/New_York", NOW)
    assert value == datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc)
    assert confidence == 95
    assert source == "explicit_calendar_date"


def test_ambiguous_time_fails_closed():
    value, confidence, source = resolve_seller_time("call me tomorrow afternoon", "America/New_York", NOW)
    assert value is None
    assert confidence == 0
    assert source == "explicit_clock_missing"


def test_missing_timezone_never_guesses():
    value, confidence, source = resolve_seller_time("tomorrow at 3pm", None, NOW)
    assert value is None
    assert confidence == 0
    assert source == "missing_preference_or_timezone"


def test_due_followup_batches_are_bounded():
    assert MAX_DUE_BATCH == 25

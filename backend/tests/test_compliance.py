from app.compliance import (
    ALLOWED_CHANNELS,
    CALL_END_HOUR,
    CALL_START_HOUR,
    CONSENT_REQUIRED,
    DNC_MAX_AGE_DAYS,
    normalize_contact,
    normalize_phone,
)


def test_phone_normalization():
    assert normalize_phone("(305) 555-1212") == "+13055551212"
    assert normalize_phone("1-305-555-1212") == "+13055551212"


def test_email_normalization():
    assert normalize_contact("email", " OWNER@EXAMPLE.COM ") == "owner@example.com"


def test_fail_closed_policy_constants():
    assert DNC_MAX_AGE_DAYS == 31
    assert CALL_START_HOUR == 8
    assert CALL_END_HOUR == 21
    assert {"automated_call", "sms"}.issubset(CONSENT_REQUIRED)
    assert {"live_call", "automated_call", "sms", "email"} == ALLOWED_CHANNELS

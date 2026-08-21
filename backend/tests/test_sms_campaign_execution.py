from types import SimpleNamespace

from app.sms_campaign_execution import MAX_APPROVAL_BATCH, _override, infer_recipient_timezone


def lead(state: str | None):
    return SimpleNamespace(property=SimpleNamespace(state=state))


def recipient(lead_id=7, contact="+13055551212"):
    return SimpleNamespace(lead_id=lead_id, contact=contact)


def test_single_zone_state_is_inferred():
    zone, source = infer_recipient_timezone(lead("GA"))
    assert zone == "America/New_York"
    assert source == "single_zone_state_inference"


def test_multi_zone_state_fails_closed_without_override():
    zone, source = infer_recipient_timezone(lead("FL"))
    assert zone is None
    assert source == "multi_zone_state_requires_exact_timezone"


def test_explicit_timezone_override_wins():
    zone, source = infer_recipient_timezone(lead("FL"), "America/Chicago")
    assert zone == "America/Chicago"
    assert source == "explicit_override"


def test_campaign_manager_batch_timezone_payload_is_honored():
    assert _override({"recipient_timezone": "America/New_York"}, recipient()) == "America/New_York"


def test_per_recipient_timezone_override_has_priority():
    payload = {
        "recipient_timezone": "America/New_York",
        "timezone_overrides": {"7": "America/Chicago"},
    }
    assert _override(payload, recipient()) == "America/Chicago"


def test_missing_state_does_not_guess_timezone():
    zone, source = infer_recipient_timezone(lead(None))
    assert zone is None
    assert source == "property_state_missing"


def test_owner_approval_batches_are_bounded():
    assert MAX_APPROVAL_BATCH == 25

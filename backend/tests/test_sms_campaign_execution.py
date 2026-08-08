from types import SimpleNamespace

from app.sms_campaign_execution import MAX_APPROVAL_BATCH, infer_recipient_timezone


def lead(state: str | None):
    return SimpleNamespace(property=SimpleNamespace(state=state))


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


def test_missing_state_does_not_guess_timezone():
    zone, source = infer_recipient_timezone(lead(None))
    assert zone is None
    assert source == "property_state_missing"


def test_owner_approval_batches_are_bounded():
    assert MAX_APPROVAL_BATCH == 25

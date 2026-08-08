from types import SimpleNamespace

from app.sms_campaign_dispatch import MAX_DISPATCH_BATCH, recipient_timezone


def recipient(evidence):
    return SimpleNamespace(evidence=evidence)


def test_dispatch_batches_are_bounded():
    assert MAX_DISPATCH_BATCH == 25


def test_dispatch_uses_recipient_timezone_captured_at_approval():
    assert recipient_timezone(recipient({"recipient_timezone": "America/New_York"})) == "America/New_York"


def test_dispatch_fails_closed_when_timezone_is_missing():
    assert recipient_timezone(recipient({})) is None
    assert recipient_timezone(recipient(None)) is None


def test_dispatch_ignores_blank_timezone_values():
    assert recipient_timezone(recipient({"recipient_timezone": "   "})) is None

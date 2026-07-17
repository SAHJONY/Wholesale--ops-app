from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.outbound_gateway import DECISION_TTL, _decision_for_request, _validate_channel_provider


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
        "created_at": datetime.utcnow(),
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
    stale = decision(created_at=datetime.utcnow() - DECISION_TTL - timedelta(seconds=1))
    with pytest.raises(HTTPException):
        _decision_for_request(FakeDb(stale), principal(), 11, 1, "sms", "+13055551212")


def test_cross_workspace_decision_is_rejected():
    with pytest.raises(HTTPException):
        _decision_for_request(FakeDb(decision(organization_id=99)), principal(), 11, 1, "sms", "+13055551212")

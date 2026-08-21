from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.sms_attribution import MILESTONES, REALIZED_REVENUE_EVENT, _amount, _realized_revenue


def test_attribution_milestones_cover_revenue_funnel():
    assert {"offer_created", "offer_accepted", "contract_signed", "assignment_closed", "assignment_fee_received"}.issubset(MILESTONES)


def test_amount_accepts_positive_numeric_values():
    assert _amount("12500.50") == Decimal("12500.50")
    assert _amount(0) == Decimal("0")


def test_amount_allows_missing_value():
    assert _amount(None) is None
    assert _amount("") is None


def test_amount_rejects_negative_values():
    with pytest.raises(HTTPException) as exc:
        _amount(-1)
    assert exc.value.status_code == 422


def test_realized_revenue_counts_fee_receipt_not_close_milestone_twice():
    events = [
        SimpleNamespace(event_type="assignment_closed", amount=30000),
        SimpleNamespace(event_type="assignment_fee_received", amount=30000),
    ]
    assert REALIZED_REVENUE_EVENT == "assignment_fee_received"
    assert _realized_revenue(events) == Decimal("30000")

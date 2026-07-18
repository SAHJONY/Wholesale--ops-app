from types import SimpleNamespace

from app.national_intelligence import _assignment_fee, _equity_proxy


def test_equity_proxy_uses_market_value_and_mortgage():
    prop = SimpleNamespace(arv=None, asking_price=None)
    score, warnings = _equity_proxy(prop, {"market_value": 200000, "mortgage_balance": 100000})
    assert score == 50
    assert warnings == []


def test_equity_proxy_marks_asking_price_estimate():
    prop = SimpleNamespace(arv=200000, asking_price=140000)
    score, warnings = _equity_proxy(prop, {})
    assert score == 30
    assert warnings


def test_equity_proxy_does_not_invent_missing_values():
    prop = SimpleNamespace(arv=None, asking_price=None)
    score, warnings = _equity_proxy(prop, {})
    assert score == 0
    assert "unavailable" in warnings[0].lower()


def test_assignment_fee_uses_available_deal_spread():
    prop = SimpleNamespace(mao=100000, asking_price=120000, arv=180000)
    assert _assignment_fee(prop) == 20000


def test_assignment_fee_is_none_without_mao():
    prop = SimpleNamespace(mao=None, asking_price=120000, arv=180000)
    assert _assignment_fee(prop) is None

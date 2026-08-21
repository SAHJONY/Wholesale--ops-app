from app.phone_os import _score, _status


def test_phone_os_status_is_supervised(monkeypatch):
    monkeypatch.setenv("VOICE_INBOUND_NUMBER", "+12164804413")
    monkeypatch.setenv("VOICE_HUMAN_TRANSFER_TARGET", "+12816628581")
    monkeypatch.setenv("BLAND_DEFAULT_FROM_NUMBER", "+13465214387")
    data = _status()
    assert data["operating_mode"] == "supervised_acquisition"
    assert data["binding_offers_allowed"] is False
    assert data["contracts_autonomous"] is False
    assert data["money_movement_autonomous"] is False


def test_score_requires_real_pillars():
    empty = _score({"motivation": None, "timeline_days": None, "condition": None, "seller_price": None, "needs_human": False})
    assert empty["pillars_captured"] == 0
    assert empty["motivation_score"] == 0
    assert empty["hot_lead"] is False

    strong = _score({"motivation": "needs to sell", "timeline_days": 14, "condition": "roof repair", "seller_price": 150000, "needs_human": False})
    assert strong["pillars_captured"] == 4
    assert strong["motivation_score"] == 100
    assert strong["hot_lead"] is True


def test_human_request_forces_handoff_without_inventing_pillars():
    result = _score({"motivation": None, "timeline_days": None, "condition": None, "seller_price": None, "needs_human": True})
    assert result["pillars_captured"] == 0
    assert result["hot_lead"] is True

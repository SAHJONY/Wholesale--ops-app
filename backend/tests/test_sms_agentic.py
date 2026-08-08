from app.sms_agentic import _deterministic, _merge_qualification


def test_opt_out_never_drafts_reply():
    result = _deterministic("STOP please")
    assert result["intent"] == "opt_out"
    assert result["stage"] == "suppressed"
    assert result["reply_draft"] is None
    assert result["next_action"] == "suppress"


def test_wrong_number_is_dead_and_not_autonomous():
    result = _deterministic("Wrong number, I don't own that house")
    assert result["intent"] == "wrong_number"
    assert result["lead_temperature"] == "dead"
    assert result["reply_draft"] is None


def test_call_request_routes_hot_handoff():
    result = _deterministic("Yes, call me tomorrow")
    assert result["intent"] == "call_request"
    assert result["lead_temperature"] == "hot"
    assert result["opportunity_score"] >= 80
    assert result["requires_human"] is True


def test_explicit_dollar_amount_is_extracted_without_inference():
    result = _deterministic("I would take $125,000")
    assert result["qualification"]["asking_price"] == 125000.0


def test_qualification_merge_preserves_known_values_when_new_turn_is_unknown():
    current = {"motivation": "inherited", "timeline_days": 21}
    extracted = {"motivation": None, "timeline_days": None, "asking_price": 90000}
    merged = _merge_qualification(current, extracted)
    assert merged["motivation"] == "inherited"
    assert merged["timeline_days"] == 21
    assert merged["asking_price"] == 90000

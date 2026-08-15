import json

import pytest
from fastapi import HTTPException

from app.realtime_voice_orchestrator import _call_id, _client_events, _parse_function_call_event


def test_parses_official_function_call_done_event_shape():
    name, call_id, args = _parse_function_call_event({
        "type": "response.function_call_arguments.done",
        "call_id": "call_001",
        "name": "get_lead_context",
        "arguments": '{"lead_id":42}',
    })
    assert name == "get_lead_context"
    assert call_id == "call_001"
    assert args == {"lead_id": 42}


def test_rejects_non_function_call_events():
    with pytest.raises(HTTPException) as exc:
        _parse_function_call_event({"type": "response.done"})
    assert exc.value.status_code == 422


def test_rejects_invalid_json_arguments():
    with pytest.raises(HTTPException) as exc:
        _parse_function_call_event({
            "type": "response.function_call_arguments.done",
            "call_id": "call_001",
            "name": "get_lead_context",
            "arguments": "not-json",
        })
    assert exc.value.status_code == 422


def test_function_output_is_returned_as_realtime_client_events():
    events = _client_events("call_001", {"saved": True, "lead_id": 42})
    assert events[0]["type"] == "conversation.item.create"
    assert events[0]["item"]["type"] == "function_call_output"
    assert events[0]["item"]["call_id"] == "call_001"
    assert json.loads(events[0]["item"]["output"])["saved"] is True
    assert events[1] == {"type": "response.create"}


def test_realtime_call_ids_are_strictly_validated():
    assert _call_id("rtc_479a275623b54bdb9b6fbae2f7cbd408") == "rtc_479a275623b54bdb9b6fbae2f7cbd408"
    with pytest.raises(HTTPException):
        _call_id("../../etc/passwd")

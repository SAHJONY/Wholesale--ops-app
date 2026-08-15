from app.agentic_voice_brain import BLOCKED_CAPABILITIES, SAFE_TOOL_NAMES, realtime_tools, session_instructions


def test_realtime_brain_can_read_memory_and_policy():
    names = {tool["name"] for tool in realtime_tools()}
    assert "get_seller_memory" in names
    assert "get_call_policy" in names
    assert names == set(SAFE_TOOL_NAMES)


def test_consequential_capabilities_are_not_exposed_as_tools():
    names = {tool["name"] for tool in realtime_tools()}
    for capability in BLOCKED_CAPABILITIES:
        assert capability not in names


def test_session_instructions_require_memory_policy_and_fact_boundaries():
    text = session_instructions().lower()
    assert "seller memory" in text
    assert "call policy" in text
    assert "never invent" in text
    assert "binding offer" in text
    assert "execute a contract" in text

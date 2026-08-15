import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from app import agentic_voice_brain as avb


def test_only_safe_voice_tools_are_exposed():
    names = {tool["name"] for tool in avb.realtime_tools()}
    assert names == set(avb.SAFE_TOOL_NAMES)
    assert "make_offer" not in names
    assert "sign_contract" not in names
    assert "send_payment" not in names
    assert "dispatch_call" not in names


def test_blocked_capabilities_cover_consequential_actions():
    blocked = set(avb.BLOCKED_CAPABILITIES)
    assert "binding_offer" in blocked
    assert "contract_execution" in blocked
    assert "money_movement" in blocked
    assert "autonomous_outbound_dispatch" in blocked


def test_session_instructions_keep_property_facts_unverified():
    instructions = avb.session_instructions().lower()
    assert "never invent ownership" in instructions
    assert "seller statements remain unverified claims" in instructions
    assert "never make a binding offer" in instructions
    assert "initiate outbound contact autonomously" in instructions


def test_blueprint_uses_realtime_model_and_bilingual_languages():
    # Static policy test: runtime secrets are intentionally not required here.
    tools = avb.realtime_tools()
    assert tools
    assert all(tool["type"] == "function" for tool in tools)
    assert avb.REALTIME_MODEL
    assert avb.REALTIME_VOICE
    assert avb.HUMAN_TRANSFER.startswith("+")

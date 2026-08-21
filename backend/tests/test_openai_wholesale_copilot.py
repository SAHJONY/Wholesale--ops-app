from app import openai_wholesale_copilot as copilot


def test_copilot_has_web_and_workspace_tools(monkeypatch):
    monkeypatch.setattr(copilot.settings, "openai_vector_store_id", None)
    tools = copilot._tool_schemas()
    assert any(tool.get("type") == "web_search" for tool in tools)
    function_names = {tool.get("name") for tool in tools if tool.get("type") == "function"}
    assert {
        "list_wholesale_skills",
        "list_deal_factory_candidates",
        "analyze_workspace_property",
        "list_verified_buyers",
    }.issubset(function_names)


def test_file_search_is_only_enabled_with_configured_vector_store(monkeypatch):
    monkeypatch.setattr(copilot.settings, "openai_vector_store_id", None)
    assert not any(tool.get("type") == "file_search" for tool in copilot._tool_schemas())
    monkeypatch.setattr(copilot.settings, "openai_vector_store_id", "vs_test")
    file_tools = [tool for tool in copilot._tool_schemas() if tool.get("type") == "file_search"]
    assert file_tools == [{"type": "file_search", "vector_store_ids": ["vs_test"]}]


def test_system_prompt_blocks_invented_facts_and_consequential_actions():
    prompt = copilot.SYSTEM_PROMPT.lower()
    assert "never invent owners" in prompt
    assert "comparable sales" in prompt
    assert "do not send offers" in prompt
    assert "sign contracts" in prompt
    assert "move money" in prompt
    assert "explicit human approval" in prompt


def test_tool_rounds_are_bounded():
    assert 1 <= copilot.MAX_TOOL_ROUNDS <= 10

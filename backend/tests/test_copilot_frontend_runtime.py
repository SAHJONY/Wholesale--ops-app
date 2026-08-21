from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "frontend" / "app" / "api" / "copilot" / "chat" / "route.ts"


def test_copilot_research_has_a_long_but_bounded_runtime():
    source = ROUTE.read_text()

    assert "export const maxDuration = 300" in source
    assert "const OPENAI_TIMEOUT_MS = 280_000" in source
    assert "max_output_tokens: 4_500" in source


def test_copilot_timeout_fails_closed_with_an_actionable_gateway_response():
    source = ROUTE.read_text()

    assert "error instanceof DOMException && error.name === 'TimeoutError'" in source
    assert "status: timedOut ? 504 : 502" in source
    assert "No action was taken" in source

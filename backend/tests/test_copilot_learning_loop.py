from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_copilot_has_governed_self_improvement_loop():
    backend = (ROOT / "backend/app/openai_wholesale_copilot.py").read_text()
    route = (ROOT / "frontend/app/api/copilot/chat/route.ts").read_text()
    page = (ROOT / "frontend/app/owner/copilot/page.tsx").read_text()

    assert '@router.get("/learning-context")' in backend
    assert '@router.post("/feedback")' in backend
    assert 'governed_outcome_feedback' in backend
    assert 'Repeated AI output is not evidence' in backend
    assert 'rewrite your own code' in route
    assert '/api/backend/openai-copilot/learning-context' in route
    assert 'institutional-grade acquisition intelligence' in route
    assert 'decisive unknowns, downside case, rejection criteria' in route
    assert 'Needs improvement' in page

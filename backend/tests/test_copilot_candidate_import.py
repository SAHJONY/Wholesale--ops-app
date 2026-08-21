from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_copilot_candidate_staging_is_source_bounded_and_deduplicated():
    backend = (ROOT / "backend/app/openai_wholesale_copilot.py").read_text()
    route = (ROOT / "frontend/app/api/copilot/import/route.ts").read_text()
    page = (ROOT / "frontend/app/owner/copilot/page.tsx").read_text()

    assert '@router.post("/import-candidates")' in backend
    assert 'openai_copilot_research' in backend
    assert 'copilot_research_candidate' in backend
    assert 'complete address and public source URL required' in backend
    assert 'duplicate_count' in backend
    assert 'Texas is excluded' in backend
    assert "type:'json_schema'" in route
    assert 'Never invent an owner, phone, email, ARV, repair cost' in route
    assert '/openai-copilot/import-candidates' in route
    assert "request('/import'" in page
    assert 'Verification required before promotion' in page

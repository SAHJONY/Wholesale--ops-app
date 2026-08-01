from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_provider_intelligence_v2_routes_and_contracts_present():
    backend = (ROOT / "backend/app/provider_intelligence.py").read_text()
    index = (ROOT / "backend/api/index.py").read_text()
    gateway = (ROOT / "frontend/app/api/provider-intelligence/[...path]/route.ts").read_text()
    page = (ROOT / "frontend/app/owner/live-data/page.tsx").read_text()

    assert 'prefix="/provider-intelligence"' in backend
    assert '@router.get("/snapshot")' in backend
    assert '@router.post("/orchestrate")' in backend
    assert 'priority_then_fallback' in backend
    assert 'provenance' in backend
    assert 'confidence' in backend
    assert 'provider_intelligence_router' in index
    assert "new Set(['snapshot','orchestrate'])" in gateway
    assert '/api/provider-intelligence' in page
    assert 'Provider Intelligence Layer' in page


def test_provider_intelligence_preserves_truth_and_safety_controls():
    backend = (ROOT / "backend/app/provider_intelligence.py").read_text()
    assert 'Texas excluded' in backend
    assert 'ownership_verified":False' in backend
    assert 'valuation_verified":False' in backend
    assert 'contact_verified":False' in backend
    assert 'external_actions":False' in backend

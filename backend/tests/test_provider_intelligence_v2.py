from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_provider_intelligence_v4_routes_and_contracts_present():
    backend = (ROOT / "backend/app/provider_intelligence.py").read_text()
    index = (ROOT / "backend/api/index.py").read_text()
    gateway = (ROOT / "frontend/app/api/provider-intelligence/[...path]/route.ts").read_text()
    page = (ROOT / "frontend/app/owner/live-data/page.tsx").read_text()

    assert 'prefix="/provider-intelligence"' in backend
    assert '@router.get("/snapshot")' in backend
    assert '@router.post("/orchestrate")' in backend
    assert '@router.post("/verify")' in backend
    assert 'priority_then_fallback' in backend
    assert 'field_level_provenance' in backend
    assert 'confidence' in backend
    assert 'provider_intelligence_router' in index
    assert "'snapshot','orchestrate','verify'" in gateway
    assert '/api/provider-intelligence' in page
    assert 'PROVIDER INTELLIGENCE V4' in page
    assert 'Canonical Property Intelligence' in page
    assert 'eligible_property_count' in backend
    assert 'Providers available' in page
    assert 'No Provider Intelligence v4 run' in page
    assert 'Checking…' in page
    assert 'AbortSignal.timeout(60000)' in gateway


def test_provider_verification_does_not_immediately_erase_verified_state():
    page = (ROOT / "frontend/app/owner/live-data/page.tsx").read_text()
    verify_block = page.split("async function verify", 1)[1].split("async function run", 1)[0]

    assert "setData(current=>" in verify_block
    assert "await load()" not in verify_block
    assert "Provider check timed out safely" in page


def test_provider_intelligence_preserves_truth_and_safety_controls():
    backend = (ROOT / "backend/app/provider_intelligence.py").read_text()
    assert 'Texas excluded' in backend
    assert 'ownership_verified":False' in backend
    assert 'valuation_verified":False' in backend
    assert 'contact_verified":False' in backend
    assert 'external_actions":False' in backend
    assert 'contact_data_redacted_by_default":True' in backend
    assert 'dnc_tcpa_screening_required":True' in backend

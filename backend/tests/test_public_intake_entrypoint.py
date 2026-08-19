from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_intake_router_is_mounted_in_vercel_entrypoint():
    source = (ROOT / "api" / "index.py").read_text()
    assert "from app.public_intake import router as public_intake_router" in source
    assert "app.include_router(public_intake_router)" in source


def test_public_intake_contract_preserves_private_owner_os():
    source = (ROOT / "app" / "public_intake.py").read_text()
    assert 'prefix="/public-intake"' in source
    assert "automated_outreach_authorized" in source
    assert "proof_of_funds_verified=False" in source

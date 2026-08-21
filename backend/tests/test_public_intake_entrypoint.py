from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def test_public_intake_router_is_mounted_in_vercel_entrypoint():
    source = (ROOT / "api" / "index.py").read_text()
    assert "from app.public_intake import router as public_intake_router" in source
    assert "app.include_router(public_intake_router)" in source


def test_public_intake_contract_preserves_private_owner_os():
    source = (ROOT / "app" / "public_intake.py").read_text()
    assert 'prefix="/public-intake"' in source
    assert "automated_outreach_authorized" in source
    assert "proof_of_funds_verified=False" in source


def test_public_front_door_and_audience_routes_are_source_controlled():
    app_root = REPO_ROOT / "frontend" / "app"
    assert (app_root / "page.tsx").is_file()
    assert (app_root / "sell" / "page.tsx").is_file()
    assert (app_root / "buyers" / "page.tsx").is_file()
    assert (app_root / "partners" / "page.tsx").is_file()
    assert (app_root / "contact" / "page.tsx").is_file()
    assert (app_root / "owner-access" / "page.tsx").is_file()

    root_source = (app_root / "page.tsx").read_text()
    assert "redirect('/owner')" not in root_source
    assert 'href="/owner-access"' in root_source


def test_auth_proxy_allows_public_root_and_still_protects_owner_os():
    source = (REPO_ROOT / "frontend" / "proxy.ts").read_text()
    assert "if (pathname === '/')" in source
    assert "return NextResponse.next();" in source
    assert "url.pathname = '/owner';" not in source
    assert "pathname === '/owner' || pathname.startsWith('/owner/')" in source
    assert "url.pathname = '/login';" in source

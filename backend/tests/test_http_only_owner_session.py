from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_owner_access_gateway_sets_secure_http_only_cookie():
    source = read("frontend/app/api/owner-access/[action]/route.ts")
    assert "httpOnly: true" in source
    assert "secure: true" in source
    assert "sameSite: 'strict'" in source
    assert "SESSION_MAX_AGE" in source
    assert "action === 'logout'" in source


def test_owner_middleware_protects_all_owner_routes():
    source = read("frontend/middleware.ts")
    assert "'/owner/:path*'" in source
    assert "request.cookies.get(SESSION_COOKIE)" in source
    assert "url.pathname = '/login'" in source
    assert "returnTo" in source


def test_provider_gateway_accepts_cookie_and_fails_closed():
    source = read("frontend/app/api/provider-intelligence/[...path]/route.ts")
    assert "request.cookies.get(SESSION_COOKIE)" in source
    assert "`Bearer ${cookieToken}`" in source
    assert "Owner session required" in source
    assert "maxAge: 0" in source


def test_provider_ui_does_not_read_owner_token_from_browser_storage():
    source = read("frontend/app/owner/live-data/page.tsx")
    assert "localStorage.getItem" not in source
    assert "credentials:'same-origin'" in source


def test_login_uses_cookie_session_and_cannot_loop_on_stale_local_storage():
    source = read("frontend/app/login/page.tsx")
    assert "/api/owner-access/session" in source
    assert "sessionData.authenticated" in source
    assert "localStorage.getItem" not in source
    assert "localStorage.setItem" not in source
    assert "localStorage.removeItem('sahjony_owner_session')" in source

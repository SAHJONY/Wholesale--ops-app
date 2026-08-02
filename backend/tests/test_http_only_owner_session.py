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


def test_owner_middleware_injects_cookie_only_into_same_origin_api_requests():
    source = read("frontend/middleware.ts")
    assert "pathname.startsWith('/api/')" in source
    assert "headers.set('authorization', `Bearer ${session}`)" in source
    assert "'/api/:path*'" in source


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


def test_owner_session_is_validated_upstream_and_stale_cookie_is_cleared():
    source = read("frontend/app/api/owner-access/[action]/route.ts")
    assert "`${BACKEND_URL}/auth/me`" in source
    assert "{ authenticated: true, principal }" in source
    assert "upstream.status === 401 || upstream.status === 403" in source
    assert "return clearSession" in source


def test_all_owner_pages_avoid_browser_token_storage_and_direct_backend_calls():
    pages = sorted((ROOT / "frontend/app/owner").glob("**/page.tsx"))
    offenders = []
    for page in pages:
        source = page.read_text()
        if "localStorage" in source or "https://backend-pi-opal-65.vercel.app" in source:
            offenders.append(str(page.relative_to(ROOT)))
    assert not offenders, f"Owner session or direct-backend usage remains in: {offenders}"


def test_generic_backend_proxy_uses_stable_backend_alias():
    source = read("frontend/app/api/backend/[...path]/route.ts")
    assert "process.env.BACKEND_URL" in source
    assert "https://backend-pi-opal-65.vercel.app" in source
    assert "wholesale-ops-2kqe2x2q1" not in source


def test_owner_navigation_exposes_every_distinct_workspace():
    navigation = read("frontend/app/owner/OwnerNavigation.tsx")
    pages = sorted((ROOT / "frontend/app/owner").glob("*/page.tsx"))
    missing = []
    for page in pages:
        route = f"/owner/{page.parent.name}"
        if route == "/owner/ceo-command":
            continue
        if f"href: '{route}'" not in navigation:
            missing.append(route)
    assert not missing, f"Owner routes missing from navigation: {missing}"

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


def test_owner_proxy_protects_all_owner_routes():
    source = read("frontend/proxy.ts")
    assert "'/owner/:path*'" in source
    assert "request.cookies.get(SESSION_COOKIE)" in source
    assert "url.pathname = '/login'" in source
    assert "returnTo" in source


def test_owner_proxy_injects_cookie_only_into_same_origin_api_requests():
    source = read("frontend/proxy.ts")
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
    assert "process.env.BACKEND_INTERNAL_URL" in source
    assert "process.env.BACKEND_URL" in source
    assert "http://localhost:8000" in source
    assert "wholesale-ops-2kqe2x2q1" not in source


def test_ceo_command_center_displays_probability_weighted_forecast():
    source = read("frontend/app/owner/ceo-command/page.tsx")
    assert "probability_weighted_revenue" in source
    assert "Probability-adjusted assignment forecast" in source


def test_owner_navigation_prioritizes_deal_workflow_and_classifies_support_surfaces():
    navigation = read("frontend/app/owner/OwnerNavigation.tsx")
    deal_routes = {
        "/owner/deal-factory",
        "/owner/attention",
        "/owner/acquisition",
        "/owner/real-deals",
        "/owner/deals",
        "/owner/buyer-intake",
        "/owner/properties",
        "/owner/phone-os",
        "/owner/communications",
        "/owner/sms-acquisition",
        "/owner/disposition",
        "/owner/closing",
        "/owner/title-companies",
        "/owner/deal-intelligence",
        "/owner/lead-verification",
        "/owner/system-health",
    }
    for route in deal_routes:
        assert f"href: '{route}'" in navigation, f"Deal workflow route missing from navigation: {route}"

    support_hidden_routes = {
        "/owner/copilot",
        "/owner/markets",
        "/owner/live-data",
        "/owner/jobs",
        "/owner/integrations",
        "/owner/provider-activation",
        "/owner/public-data",
        "/owner/audit",
        "/owner/security",
        "/owner/sessions",
        "/owner/activate",
        "/owner/go-live",
        "/owner/real-estate-intelligence",
    }
    pages = sorted((ROOT / "frontend/app/owner").glob("*/page.tsx"))
    unexpected_hidden = []
    for page in pages:
        route = f"/owner/{page.parent.name}"
        if route == "/owner/ceo-command" or route in support_hidden_routes:
            continue
        if route != "/owner" and f"href: '{route}'" not in navigation:
            unexpected_hidden.append(route)
    assert not unexpected_hidden, f"Unclassified owner routes missing from deal-first navigation: {unexpected_hidden}"

from api.index import app
from app.deployment_diagnostics import CRITICAL_ROUTES, registered_route_paths


def test_vercel_entrypoint_registers_all_critical_routes():
    paths = registered_route_paths(app)
    missing = [path for path in CRITICAL_ROUTES if path not in paths]
    assert not missing, f"Missing production routes: {missing}"


def test_openapi_generation_succeeds():
    schema = app.openapi()
    assert schema["info"]["title"] == "SAHJONY Wholesale Ops API"
    for path in CRITICAL_ROUTES:
        assert path in schema["paths"], f"Route absent from OpenAPI: {path}"

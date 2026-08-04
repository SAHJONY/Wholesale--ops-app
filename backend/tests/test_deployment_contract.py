from pathlib import Path

from api.index import app
from app.deployment_diagnostics import CRITICAL_ROUTES, registered_route_paths

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _declared_names(text: str) -> list[str]:
    return [
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    ]


def test_vercel_entrypoint_registers_all_critical_routes():
    paths = registered_route_paths(app)
    missing = [path for path in CRITICAL_ROUTES if path not in paths]
    assert not missing, f"Missing production routes: {missing}"


def test_openapi_generation_succeeds():
    schema = app.openapi()
    assert schema["info"]["title"] == "SAHJONY Wholesale Ops API"
    for path in CRITICAL_ROUTES:
        assert path in schema["paths"], f"Route absent from OpenAPI: {path}"


def test_env_example_declares_each_variable_exactly_once():
    """A repeated name is a silent trap, not a cosmetic one.

    Every dotenv loader takes the last assignment, so an operator who fills in
    the first copy and leaves the second blank ends up with an empty value while
    the file looks answered. SMARTY_AUTH_ID, SMARTY_AUTH_TOKEN and
    CENSUS_API_KEY were each declared twice, in sections far enough apart that
    neither copy was visible from the other.
    """
    names = _declared_names(ENV_EXAMPLE.read_text())
    duplicated = sorted({name for name in names if names.count(name) > 1})
    assert not duplicated, (
        f"declared more than once in .env.example: {duplicated}. The last "
        "assignment wins, so filling in only the first leaves it unset."
    )

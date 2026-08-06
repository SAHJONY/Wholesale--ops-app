from pathlib import Path

from api.index import app
from app.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_schema_mode_defaults_to_strict(monkeypatch):
    monkeypatch.delenv("SCHEMA_MODE", raising=False)
    assert Settings(_env_file=None).schema_mode == "strict"


def test_runtime_does_not_create_database_schema():
    runtime_files = [ROOT / "backend/app/main.py", ROOT / "backend/api/index.py"]
    runtime_files.extend((ROOT / "backend/app").glob("*.py"))
    offenders = [str(path.relative_to(ROOT)) for path in runtime_files if "metadata.create_all" in path.read_text()]
    assert not offenders, f"Runtime schema creation remains in: {offenders}"


def test_runtime_does_not_use_naive_utcnow():
    runtime_files = (ROOT / "backend/app").glob("*.py")
    offenders = [str(path.relative_to(ROOT)) for path in runtime_files if "datetime.utcnow" in path.read_text()]
    assert not offenders, f"Naive UTC calls remain in: {offenders}"


def test_every_api_operation_is_published_in_openapi():
    schema = app.openapi()
    methods = {"get", "post", "put", "patch", "delete"}
    expected = {
        (route.path, method.lower())
        for route in app.routes
        for method in (route.methods or set())
        if method.lower() in methods and getattr(route, "include_in_schema", True)
    }
    published = {
        (path, method)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in methods
    }
    assert published == expected
    assert len(published) >= 167


def test_all_owner_pages_are_present_and_nonempty():
    # Floor lowered from 30 to 27 when thirteen reporting dashboards were
    # retired and the ceo-command page restored. The number is a tripwire for
    # pages disappearing by accident, so it tracks the deliberate count rather
    # than staying at a value no tree can satisfy.
    pages = sorted((ROOT / "frontend/app/owner").glob("**/page.tsx"))
    assert len(pages) >= 27
    assert all(
    (
        "export default" in page.read_text()
        or "export { default }" in page.read_text()
    )
    for page in pages
)


def test_frontend_workspace_uses_only_root_lockfile():
    assert (ROOT / "package-lock.json").is_file()
    assert not (ROOT / "frontend/package-lock.json").exists()

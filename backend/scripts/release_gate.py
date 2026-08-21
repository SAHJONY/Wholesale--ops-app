from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api.index import app  # noqa: E402
from app.database import Base, engine  # noqa: E402


REQUIRED_ROUTES = {
    "/health",
    "/human-auth/login",
    "/deployment/status",
    "/national-intelligence/snapshot",
    "/real-estate-intelligence/snapshot",
    "/data-intake/snapshot",
    "/buyer-intake/snapshot",
    "/test-deal/snapshot",
    "/jobs/snapshot",
    "/audit/snapshot",
    "/security/snapshot",
    "/continuity/snapshot",
}

# The build is not production-ready when a headline snapshot exists but a
# revenue-critical router has disappeared or been replaced by a placeholder.
# Prefix coverage guards the full operational path without coupling this gate
# to every individual endpoint implementation.
REQUIRED_ROUTE_PREFIXES = {
    "/lead-verification",
    "/deal-intelligence",
    "/deal-execution",
    "/buyer-matching",
    "/disposition",
    "/closing-command",
    "/title-company-matching",
    "/integration-hub",
    "/integration-reliability",
}

REQUIRED_MODELS = {
    "property_intelligence_scores",
    "national_intelligence_runs",
    "background_jobs",
}


def main() -> int:
    routes = {getattr(route, "path", "") for route in app.routes}
    metadata_tables = set(Base.metadata.tables)

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    database_tables: set[str] = set()
    database_error: str | None = None
    try:
        database_tables = set(inspect(engine).get_table_names())
    except Exception as exc:  # pragma: no cover - depends on deployment DB availability
        database_error = f"{type(exc).__name__}: {exc}"

    missing_routes = sorted(REQUIRED_ROUTES - routes)
    missing_route_prefixes = sorted(
        prefix for prefix in REQUIRED_ROUTE_PREFIXES
        if not any(route == prefix or route.startswith(f"{prefix}/") for route in routes)
    )
    missing_models = sorted(REQUIRED_MODELS - metadata_tables)
    missing_database_tables = sorted(REQUIRED_MODELS - database_tables) if not database_error else []

    result = {
        "release_ready": not missing_routes
        and not missing_route_prefixes
        and not missing_models
        and len(heads) == 1
        and not database_error
        and not missing_database_tables,
        "routes": {
            "required": len(REQUIRED_ROUTES),
            "missing": missing_routes,
            "required_prefixes": sorted(REQUIRED_ROUTE_PREFIXES),
            "missing_prefixes": missing_route_prefixes,
        },
        "models": {"required": len(REQUIRED_MODELS), "missing": missing_models},
        "migrations": {"heads": heads, "single_head": len(heads) == 1},
        "database": {
            "reachable": database_error is None,
            "error": database_error,
            "missing_required_tables": missing_database_tables,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

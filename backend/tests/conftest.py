"""Test-suite bootstrap.

Production runs under ``schema_mode="strict"``: Alembic owns the schema and the
application never issues DDL at startup (enforced by
``test_production_hardening.test_runtime_does_not_create_database_schema``).
That leaves the test suite with no schema at all, which is why the ``test_api``
integration tests were failing against a table-less database.

Creating the schema here keeps the strict runtime guarantee intact — this file
is test-only and outside the paths that guard checks — while giving TestClient
tests real tables to work against.

The database URL is set before any application module is imported, because
``app.database`` builds its engine at import time from ``Settings``.
"""

from __future__ import annotations

import os
from pathlib import Path

# Must match the URL test_api.py sets, so both resolve to the same engine
# regardless of which module the interpreter imports first.
TEST_DATABASE_URL = "sqlite:///./test_wholesale_ops.db"
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)

# API tests need to create more than one workspace, and /auth/bootstrap locks
# itself once the first organization exists. Setting a known secret here lets
# tests provision isolated workspaces without weakening the production default,
# which stays locked whenever BOOTSTRAP_SECRET is unset.
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret")

import pytest  # noqa: E402

from app.database import Base, engine  # noqa: E402

# Importing the Vercel entrypoint registers every router, which in turn imports
# every model module. Without it, `Base.metadata` would only hold the subset of
# tables reachable from whichever test module happened to be collected first.
import api.index  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _database_schema():
    """Create the full schema once per session and clean up afterwards."""
    Base.metadata.create_all(engine)
    yield
    engine.dispose()
    if engine.url.database and engine.url.get_backend_name() == "sqlite":
        Path(engine.url.database).unlink(missing_ok=True)

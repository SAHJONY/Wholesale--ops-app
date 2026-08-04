"""Make the test schema a precondition the suite establishes for itself.

Every test module points DATABASE_URL at ``./test_wholesale_ops.db`` and then
assumes the tables are already there. Nothing in the suite creates them --
CI does it out-of-band by running ``alembic upgrade head`` before pytest. On
a clean checkout that step is invisible, so ``pytest -q`` fails roughly eighty
tests with ``no such table: app_users``, which reads like a broken suite
rather than a missing setup step. The file is untracked, so once it exists
locally the failures disappear and never come back, which makes the problem
hard to see twice.

This runs the same migration CI runs, but only when the schema is actually
absent and only against SQLite. Auto-migrating an arbitrary DATABASE_URL
would mean a developer whose shell still points at a real database could
destroy it by running the tests, so a non-SQLite target with a missing
schema is reported instead of repaired.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Must be set before anything imports app.config, which resolves the engine URL
# at import time. conftest is imported ahead of every test module, so this is
# the one place that can establish it for the whole run. Individual modules use
# setdefault against the same value, so an explicit DATABASE_URL still wins.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")
os.environ.setdefault("APP_URL", "http://localhost:3000")

# /auth/bootstrap locks itself once the first organization exists, so tests that
# need more than one workspace require a known secret. Production stays locked
# whenever BOOTSTRAP_SECRET is unset, which is the default outside tests.
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret")

# A table from the earliest schema and one from the most recent migration: the
# pair distinguishes "no schema at all" from "schema stopped partway".
REQUIRED_TABLES = ("app_users", "properties", "background_jobs")


def _missing_tables() -> list[str]:
    from sqlalchemy import inspect

    from app.database import engine

    present = set(inspect(engine).get_table_names())
    return [name for name in REQUIRED_TABLES if name not in present]


def _bootstrap_schema() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")


def pytest_configure(config) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from app.database import database_url

    try:
        missing = _missing_tables()
    except SQLAlchemyError as exc:
        # Reaching the database is a precondition for every test here, so an
        # unreachable one is worth naming now rather than as 141 identical
        # connection errors.
        raise RuntimeError(
            f"Cannot reach DATABASE_URL={database_url!r}: {exc}"
        ) from exc
    if not missing:
        return

    if not database_url.startswith("sqlite"):
        raise RuntimeError(
            f"DATABASE_URL={database_url!r} is missing tables {missing}. "
            "Refusing to migrate a non-SQLite database from the test suite; run "
            "'alembic upgrade head' deliberately, or point DATABASE_URL at a "
            "throwaway SQLite file."
        )

    _bootstrap_schema()

    still_missing = _missing_tables()
    if still_missing:
        raise RuntimeError(
            f"Migrations ran but {still_missing} are still absent. The schema and "
            "the migration history have diverged."
        )

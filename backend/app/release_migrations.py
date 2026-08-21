from __future__ import annotations

import hmac
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import inspect, text

from .database import engine

router = APIRouter(prefix="/release", tags=["release migrations"])
BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOCK_NAME = "sahjony_wholesale_ops_alembic"


def _authorize(request: Request) -> None:
    expected = str(os.getenv("MIGRATION_RELEASE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(503, "Migration release bridge is not configured")
    authorization = str(request.headers.get("authorization") or "")
    supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid migration release authorization")


def _config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


@router.post("/migrate")
def migrate_production(request: Request):
    """Upgrade the Vercel-managed database without exporting its credential."""
    _authorize(request)
    if engine.dialect.name != "postgresql":
        raise HTTPException(503, "Release migrations require the production PostgreSQL database")

    config = _config()
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise HTTPException(409, f"Expected one migration head; found {len(heads)}")
    expected_head = heads[0]

    try:
        with engine.begin() as connection:
            connection.execute(text("select pg_advisory_lock(hashtext(:name))"), {"name": LOCK_NAME})
            try:
                tables = set(inspect(connection).get_table_names())
                previous = connection.execute(text("select version_num from alembic_version")).scalar_one_or_none() if "alembic_version" in tables else None
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                current = connection.execute(text("select version_num from alembic_version")).scalar_one_or_none()
            finally:
                connection.execute(text("select pg_advisory_unlock(hashtext(:name))"), {"name": LOCK_NAME})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Production migration failed; inspect protected runtime logs") from exc

    if current != expected_head:
        raise HTTPException(500, "Production database did not reach the expected migration head")
    return {
        "status": "current",
        "previous_revision": previous,
        "current_revision": current,
        "expected_head": expected_head,
        "migrated": previous != current,
        "database_credential_exported": False,
    }

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


@dataclass(frozen=True)
class SchemaPolicyState:
    environment: str
    mode: str
    metadata_tables: int
    database_tables: int
    missing_tables: list[str]
    runtime_create_attempted: bool
    strict_ready: bool
    error: str | None = None


_STATE: SchemaPolicyState | None = None


def _environment() -> str:
    return (
        os.getenv("VERCEL_ENV")
        or os.getenv("RAILWAY_ENVIRONMENT_NAME")
        or os.getenv("APP_ENV")
        or "development"
    ).lower()


def configure_schema(base: type[DeclarativeBase], engine: Engine) -> SchemaPolicyState:
    """Inspect schema drift without mutating the schema at application startup."""
    global _STATE

    environment = _environment()
    mode = "strict"
    metadata_tables = set(base.metadata.tables)
    runtime_create_attempted = False

    try:
        database_tables = set(inspect(engine).get_table_names())
        missing = sorted(metadata_tables - database_tables)

        _STATE = SchemaPolicyState(
            environment=environment,
            mode=mode,
            metadata_tables=len(metadata_tables),
            database_tables=len(database_tables),
            missing_tables=missing,
            runtime_create_attempted=runtime_create_attempted,
            strict_ready=not missing,
        )
    except Exception as exc:  # startup must remain diagnosable rather than opaque
        _STATE = SchemaPolicyState(
            environment=environment,
            mode=mode,
            metadata_tables=len(metadata_tables),
            database_tables=0,
            missing_tables=sorted(metadata_tables),
            runtime_create_attempted=runtime_create_attempted,
            strict_ready=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    return _STATE


def schema_policy_snapshot() -> dict:
    if _STATE is None:
        return {
            "environment": _environment(),
            "mode": "uninitialized",
            "metadata_tables": 0,
            "database_tables": 0,
            "missing_tables": [],
            "runtime_create_attempted": False,
            "strict_ready": False,
            "error": "Schema policy has not been initialized",
        }
    return asdict(_STATE)

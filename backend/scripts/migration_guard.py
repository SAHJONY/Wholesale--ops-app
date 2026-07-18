from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"


def config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    url = os.getenv("DATABASE_URL")
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def expected_head(cfg: Config) -> str:
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one migration head, found {heads}")
    return heads[0]


def current_revision(database_url: str) -> tuple[str | None, bool]:
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables:
            return None, bool(tables)
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one_or_none()
        return revision, True


def status() -> dict:
    cfg = config()
    head = expected_head(cfg)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return {"state": "database_url_missing", "head": head, "current": None, "release_ready": False}
    current, schema_present = current_revision(database_url)
    if current == head:
        state = "current"
    elif current is None and schema_present:
        state = "unversioned_existing_schema"
    elif current is None:
        state = "empty_database"
    else:
        state = "behind_or_diverged"
    return {
        "state": state,
        "head": head,
        "current": current,
        "schema_present": schema_present,
        "release_ready": state == "current",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SAHJONY database migration state")
    parser.add_argument("--allow-unversioned-baseline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = status()
    print(json.dumps(result, indent=2) if args.json else result)
    if result["release_ready"]:
        return 0
    if args.allow_unversioned_baseline and result["state"] == "unversioned_existing_schema":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

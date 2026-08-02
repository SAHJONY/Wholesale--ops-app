from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_batchdata_oauth_schema_upgrades_from_previous_head(tmp_path: Path) -> None:
    database_path = tmp_path / "batchdata_oauth.db"
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "20260721_0004"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())
    assert "batchdata_oauth_connections" in tables
    assert "batchdata_oauth_states" in tables
    assert "alembic_version" in tables

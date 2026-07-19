from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_alembic(database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_national_intelligence_schema_upgrades_from_baseline(tmp_path: Path) -> None:
    database_path = tmp_path / "migration_contract.db"
    database_url = f"sqlite:///{database_path}"

    _run_alembic(database_url, "stamp", "20260718_0001")
    _run_alembic(database_url, "upgrade", "head")

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())
    assert "property_intelligence_scores" in tables
    assert "national_intelligence_runs" in tables
    assert "alembic_version" in tables

    score_indexes = {item["name"] for item in inspector.get_indexes("property_intelligence_scores")}
    assert "ix_property_intelligence_scores_organization_id" in score_indexes
    assert "ix_property_intelligence_scores_opportunity_score" in score_indexes

    unique_constraints = {
        item["name"] for item in inspector.get_unique_constraints("property_intelligence_scores")
    }
    assert "uq_property_intelligence_org_property" in unique_constraints

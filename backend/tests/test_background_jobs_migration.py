from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_background_jobs_schema_is_created_from_baseline(tmp_path: Path, monkeypatch):
    database = tmp_path / "migration.db"
    database_url = f"sqlite:///{database}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.stamp(config, "20260718_0001")
    command.upgrade(config, "head")

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())
    assert "background_jobs" in tables

    indexes = {row["name"] for row in inspector.get_indexes("background_jobs")}
    assert "ix_background_jobs_organization_id" in indexes
    assert "ix_background_jobs_status" in indexes
    assert "ix_background_jobs_available_at" in indexes

from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.release_migrations import _authorize

ROOT = Path(__file__).resolve().parents[2]


def request(token: str | None = None) -> Request:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/release/migrate", "headers": headers})


def test_release_bridge_fails_closed_without_runtime_token(monkeypatch):
    monkeypatch.delenv("MIGRATION_RELEASE_TOKEN", raising=False)
    with pytest.raises(HTTPException) as error:
        _authorize(request("anything"))
    assert error.value.status_code == 503


def test_release_bridge_uses_constant_time_bearer_authorization(monkeypatch):
    monkeypatch.setenv("MIGRATION_RELEASE_TOKEN", "release-secret")
    _authorize(request("release-secret"))
    with pytest.raises(HTTPException) as error:
        _authorize(request("wrong-secret"))
    assert error.value.status_code == 401


def test_alembic_runtime_accepts_locked_supplied_connection():
    source = (ROOT / "backend/migrations/env.py").read_text()
    assert 'config.attributes.get("connection")' in source
    assert "migrate(supplied_connection)" in source


def test_deploy_workflow_never_exports_production_database_url():
    source = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "PRODUCTION_DATABASE_URL" not in source
    assert "MIGRATION_RELEASE_TOKEN" in source
    assert "/api/backend/release/migrate" in source

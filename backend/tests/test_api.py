import os

os.environ["DATABASE_URL"] = "sqlite:///./test_wholesale_ops.db"

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health_remains_public():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_legacy_global_operations_are_retired():
    requests = [
        ("GET", "/dashboard", None),
        ("GET", "/leads", None),
        ("POST", "/leads", {}),
        ("POST", "/buyers", {}),
        ("POST", "/underwrite", {}),
        ("GET", "/autonomy/status", None),
        ("POST", "/autonomy/run", {}),
        ("POST", "/autonomy/tasks", {}),
        ("POST", "/autonomy/execute", {}),
        ("POST", "/acquisition/schedule", {}),
        ("GET", "/deals", None),
        ("GET", "/executive/brief", None),
        ("POST", "/approvals/1/decision", {"decision": "approved"}),
    ]
    for method, path, payload in requests:
        response = client.request(method, path, json=payload)
        assert response.status_code == 410, (method, path, response.text)
        assert "authenticated workspace endpoint" in response.json()["detail"]


def test_bland_webhook_fails_closed_without_secret(monkeypatch):
    monkeypatch.setattr("app.main.settings.bland_webhook_secret", None)
    response = client.post("/webhooks/bland", json={"call_id": "test-call"})
    assert response.status_code == 503


def test_bland_webhook_requires_configured_secret(monkeypatch):
    monkeypatch.setattr("app.main.settings.bland_webhook_secret", "expected-secret")
    unauthorized = client.post("/webhooks/bland", json={"call_id": "test-call"})
    assert unauthorized.status_code == 401

    accepted = client.post(
        "/webhooks/bland",
        headers={"x-webhook-secret": "expected-secret"},
        json={"call_id": "test-call", "direction": "inbound", "status": "completed"},
    )
    assert accepted.status_code == 200


def test_cron_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    response = client.get("/cron/operations")
    assert response.status_code == 503


def test_cron_rejects_missing_authorization(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    response = client.get("/cron/operations")
    assert response.status_code == 401

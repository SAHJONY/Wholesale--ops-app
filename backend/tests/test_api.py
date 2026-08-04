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


def test_the_legacy_bland_webhook_is_retired_and_names_its_replacement():
    # It authenticated with `!=` against a secret read from BLAND_WEBHOOK_SECRET,
    # a name nothing sets, and it wrote the call row without going through
    # record_call() -- so a spoken opt-out arriving here was stored and never
    # acted on. A 410 naming the signed path beats a 404 that reads as an outage.
    response = client.post("/webhooks/bland", json={"call_id": "test-call"})
    assert response.status_code == 410
    assert "/voice/webhooks/bland" in response.json()["detail"]


def test_the_retired_webhook_accepts_nothing_even_with_the_old_header():
    # The old caller presented this header. It must not be a way back in.
    response = client.post(
        "/webhooks/bland",
        headers={"x-webhook-secret": "expected-secret"},
        json={"call_id": "test-call", "direction": "inbound", "status": "completed"},
    )
    assert response.status_code == 410


def test_no_setting_binds_an_unread_bland_env_name():
    # Every Bland call site reads BLAND_AI_*. A Settings field named bland_*
    # binds the short name, and a short name that is set but read nowhere is a
    # configuration that looks complete and does nothing -- which is exactly how
    # the retired webhook spent its life answering 503.
    from app.config import Settings

    bound = [name for name in Settings.model_fields if name.startswith("bland")]
    assert not bound, f"these bind unread BLAND_* env names: {bound}"


def test_cron_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    response = client.get("/cron/operations")
    assert response.status_code == 503


def test_cron_rejects_missing_authorization(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    response = client.get("/cron/operations")
    assert response.status_code == 401

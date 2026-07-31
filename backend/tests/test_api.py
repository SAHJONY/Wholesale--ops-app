import os

os.environ["DATABASE_URL"] = "sqlite:///./test_wholesale_ops.db"

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_underwrite():
    response = client.post(
        "/underwrite",
        json={"arv": 250000, "repairs": 50000, "assignment_fee": 15000, "mao_factor": 0.70},
    )
    assert response.status_code == 200
    assert response.json()["mao"] == 110000


def create_test_lead():
    payload = {
        "seller_name": "Test Seller",
        "phone": "+15555550100",
        "motivation_score": 80,
        "equity_score": 75,
        "property": {
            "address": "100 Test Ave",
            "city": "Pensacola",
            "state": "FL",
            "zip_code": "32501",
            "arv": 250000,
            "repairs": 50000,
            "distress_signals": ["vacant", "code_violation"],
        },
    }
    return client.post("/leads", json=payload)


def test_create_and_list_lead():
    created = create_test_lead()
    assert created.status_code == 200
    assert created.json()["mao"] == 110000
    assert created.json()["autonomy_task_id"] > 0

    listed = client.get("/leads")
    assert listed.status_code == 200
    assert any(item["seller_name"] == "Test Seller" for item in listed.json())


def test_bland_webhook():
    response = client.post(
        "/webhooks/bland",
        json={"call_id": "test-call-1", "direction": "inbound", "status": "completed", "summary": "Qualified seller"},
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "call_id": "test-call-1"}


def test_autonomous_task_execution():
    created = create_test_lead()
    assert created.status_code == 200

    run = client.post(
        "/autonomy/run",
        json={"agent_name": "executive-orchestrator", "objective": "Run daily wholesale operations"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "completed"

    executed = client.post("/autonomy/execute", json={"limit": 20})
    assert executed.status_code == 200
    assert executed.json()["executed"] >= 1

    status = client.get("/autonomy/status")
    assert status.status_code == 200
    assert status.json()["mode"] == "supervised_autonomous"
    assert len(status.json()["agents"]) >= 6


def test_disposition_requires_approval():
    created = create_test_lead()
    property_id = created.json()["property_id"]

    buyer = client.post(
        "/buyers",
        json={
            "name": "Test Buyer", "phone": "+15555550200",
            "zip_codes": ["32501"], "asset_types": ["single_family"],
            "min_price": 50000, "max_price": 200000, "max_rehab": 75000,
            "closing_days": 10, "proof_of_funds_verified": True,
            "response_rate": 85, "reliability_score": 90,
        },
    )
    assert buyer.status_code == 200

    queued = client.post(f"/autonomy/disposition/{property_id}")
    assert queued.status_code == 200
    assert queued.json()["approval_gate"] is True

    executed = client.post("/autonomy/execute", json={"limit": 20})
    assert executed.status_code == 200

    status = client.get("/autonomy/status").json()
    pending = [item for item in status["approvals"] if item["status"] == "pending"]
    assert pending

    decision = client.post(
        f"/approvals/{pending[0]['id']}/decision",
        json={"decision": "approved", "decided_by": "test-owner"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"

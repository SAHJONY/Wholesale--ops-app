import os

os.environ["DATABASE_URL"] = "sqlite:///./test_wholesale_ops.db"

from fastapi.testclient import TestClient
from app.main import app

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


def test_create_and_list_lead():
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
    created = client.post("/leads", json=payload)
    assert created.status_code == 200
    assert created.json()["mao"] == 110000

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

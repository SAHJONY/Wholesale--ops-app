import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import business_email

ROOT = Path(__file__).resolve().parents[2]


def test_all_departmental_addresses_use_verified_business_domain():
    payload = json.loads((ROOT / "config/business-email-departments.json").read_text())
    departments = payload["departments"]

    assert set(departments) == {
        "acquisitions", "dispositions", "title_closing", "underwriting",
        "compliance", "operations", "support", "executive",
    }
    addresses = {value["email"] for value in departments.values()}
    assert len(addresses) == len(departments)
    assert all(address.endswith("@sahjony.com") for address in addresses)


def test_department_sender_policy_rejects_unapproved_domains(monkeypatch):
    monkeypatch.setattr(business_email, "_department_config", lambda: {"acquisitions": ("Acquisitions", "outside@example.com")})
    with pytest.raises(HTTPException) as error:
        business_email._sender_for("acquisitions")
    assert error.value.status_code == 503


def test_subject_tags_preserve_deal_and_lead_routing():
    assert business_email._tag_subject("Offer update", 12, None) == "[Deal #12] Offer update"
    assert business_email._tag_subject("Seller reply", None, 24) == "[Lead #24] Seller reply"


def test_public_readiness_route_is_mounted():
    source = (ROOT / "backend/api/index.py").read_text()
    assert "business_email_public_router" in source
    assert "app.include_router(business_email_public_router)" in source

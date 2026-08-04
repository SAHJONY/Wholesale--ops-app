"""Lead verification gate: a lead is actionable only when its property is a
real, locatable place.

Census payloads are TEST FIXTURES mirroring the live wire shape.
"""

import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient

from api.index import app
from app import lead_verification, nationwide_public_data, security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization, WorkspaceEntity
from app.database import SessionLocal
from app.models import Lead, Property
from tests.test_verified_ingest import ACS_FIXTURE, GEOCODER_FIXTURE

client = TestClient(app)


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()
    os.environ.pop(lead_verification.ENFORCE_ENV, None)


teardown_function = setup_function


def _patch_census(monkeypatch):
    async def fake_request_json(url, params):
        if url == nationwide_public_data.CENSUS_ACS_URL:
            return ACS_FIXTURE, 12, 0
        return GEOCODER_FIXTURE, 30, 0
    monkeypatch.setattr(nationwide_public_data, "_request_json", fake_request_json)


def _workspace(role="manager"):
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"LV Org {suffix}", slug=f"lv-org-{suffix}")
        user = AppUser(email=f"lv-{suffix}@example.com", name="Ops")
        db.add_all([organization, user])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=user.id, role=role),
            ApiCredential(organization_id=organization.id, user_id=user.id, name="key",
                          key_prefix=key[:18], key_hash=_hash_key(key)),
        ])
        db.commit()
        return key, organization.id
    finally:
        db.close()


def _lead(organization_id, address="1600 Pennsylvania Ave NW", city="Washington", state="DC", zip_code="20500"):
    db = SessionLocal()
    try:
        lead = Lead(seller_name="Unverified Entry", phone="+15555550000")
        db.add(lead)
        db.flush()
        prop = Property(lead_id=lead.id, address=address, city=city, state=state, zip_code=zip_code)
        db.add(prop)
        db.flush()
        db.add(WorkspaceEntity(organization_id=organization_id, entity_type="property", entity_id=prop.id))
        db.commit()
        return lead.id, prop.id
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def _verify(key, property_id):
    response = client.post("/verified-ingest/commit", headers=_auth(key), json={"property_ids": [property_id]})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_new_lead_starts_quarantined():
    key, organization_id = _workspace()
    lead_id, _ = _lead(organization_id)
    body = client.get("/lead-verification/status", headers=_auth(key)).json()
    assert body["summary"]["verified_and_locatable"] == 0
    assert body["summary"]["quarantined"] == 1
    assert body["quarantined"][0]["lead_id"] == lead_id
    assert body["quarantined"][0]["map_url"] is None


def test_unverified_lead_cannot_be_actioned():
    key, organization_id = _workspace()
    lead_id, _ = _lead(organization_id)
    response = client.post("/lead-verification/assert-actionable", headers=_auth(key), json={"lead_id": lead_id})
    assert response.status_code == 409, response.text
    assert "not verified" in response.text


def test_verification_makes_a_lead_actionable_and_mappable(monkeypatch):
    _patch_census(monkeypatch)
    key, organization_id = _workspace()
    lead_id, property_id = _lead(organization_id)

    _verify(key, property_id)

    body = client.get(f"/lead-verification/lead/{lead_id}", headers=_auth(key)).json()
    assert body["verified"] is True
    assert body["actionable"] is True
    assert body["coordinate"]["latitude"] == 38.89768
    # The link is what "locatable by Google Maps" means in practice.
    assert body["map_url"] == "https://www.google.com/maps/search/?api=1&query=38.89768,-77.03654"

    response = client.post("/lead-verification/assert-actionable", headers=_auth(key), json={"lead_id": lead_id})
    assert response.status_code == 200, response.text


def test_verified_coordinate_is_persisted_on_the_property(monkeypatch):
    """The facts table is evidence; these columns are what map links read."""
    _patch_census(monkeypatch)
    key, organization_id = _workspace()
    _, property_id = _lead(organization_id)
    _verify(key, property_id)

    db = SessionLocal()
    try:
        prop = db.get(Property, property_id)
        assert prop.latitude == 38.89768
        assert prop.longitude == -77.03654
    finally:
        db.close()


def test_coverage_reports_the_share_of_real_leads(monkeypatch):
    _patch_census(monkeypatch)
    key, organization_id = _workspace()
    _lead(organization_id, address="111 Unverified Rd", zip_code="20501")
    _, verified_property = _lead(organization_id)
    _verify(key, verified_property)

    body = client.get("/lead-verification/status", headers=_auth(key)).json()
    assert body["summary"]["total_leads"] == 2
    assert body["summary"]["verified_and_locatable"] == 1
    assert body["summary"]["coverage_percent"] == 50.0


def test_a_property_the_geocoder_rejects_stays_quarantined(monkeypatch):
    """Texas is excluded, so it can never become actionable."""
    _patch_census(monkeypatch)
    key, organization_id = _workspace()
    lead_id, property_id = _lead(organization_id, address="123 Main St", city="Houston", state="TX", zip_code="77002")
    _verify(key, property_id)

    response = client.post("/lead-verification/assert-actionable", headers=_auth(key), json={"lead_id": lead_id})
    assert response.status_code == 409


def test_enforcement_can_be_disabled_but_is_reported():
    os.environ[lead_verification.ENFORCE_ENV] = "false"
    key, organization_id = _workspace()
    lead_id, _ = _lead(organization_id)
    body = client.get("/lead-verification/status", headers=_auth(key)).json()
    assert body["enforcement_enabled"] is False
    response = client.post("/lead-verification/assert-actionable", headers=_auth(key), json={"lead_id": lead_id})
    assert response.status_code == 200


def test_enforcement_is_on_by_default():
    assert lead_verification.enforcement_enabled() is True


def test_another_workspace_lead_is_not_visible():
    _, other_org = _workspace()
    lead_id, _ = _lead(other_org)
    key, _ = _workspace()
    assert client.get(f"/lead-verification/lead/{lead_id}", headers=_auth(key)).status_code == 404

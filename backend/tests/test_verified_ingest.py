"""Verified-ingest pipeline.

The Census payloads below are hand-built TEST FIXTURES that mirror the wire
shape of the real service. They are not real property records and must never
be loaded into an application database as if they were.
"""

import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.index import app
from app import nationwide_public_data, security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization, WorkspaceEntity
from app.database import SessionLocal
from app.intelligence_models import IntelligenceFact
from app.models import Lead, Property

client = TestClient(app)


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()


GEOCODER_FIXTURE = {
    "result": {
        "addressMatches": [{
            "matchedAddress": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
            "coordinates": {"x": -77.03654, "y": 38.89768},
            "addressComponents": {
                "fromAddress": "1600",
                "preDirection": "",
                "preType": "",
                "streetName": "PENNSYLVANIA",
                "suffixType": "AVE",
                "suffixDirection": "NW",
                "city": "WASHINGTON",
                "state": "DC",
                "zip": "20500",
            },
            "geographies": {
                "States": [{"STATE": "11"}],
                "Counties": [{"STATE": "11", "COUNTY": "001", "GEOID": "11001", "NAME": "District of Columbia"}],
                "Census Tracts": [{"STATE": "11", "COUNTY": "001", "TRACT": "006202", "GEOID": "11001006202"}],
                "Census Block Groups": [{"BLKGRP": "1", "GEOID": "110010062021"}],
                "2020 Census Blocks": [{"BLOCK": "1000", "GEOID": "110010062021000"}],
            },
        }]
    }
}

ACS_FIXTURE = [
    ["NAME", "B01003_001E", "B25064_001E", "B25077_001E", "B25001_001E", "state", "county"],
    ["District of Columbia", "671803", "1737", "705000", "358534", "11", "001"],
]


def _patch_census(monkeypatch, geocoder=GEOCODER_FIXTURE):
    async def fake_request_json(url, params):
        if url == nationwide_public_data.CENSUS_ACS_URL:
            return ACS_FIXTURE, 12, 0
        return geocoder, 30, 0

    monkeypatch.setattr(nationwide_public_data, "_request_json", fake_request_json)


def _manager_workspace():
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"Ingest Org {suffix}", slug=f"ingest-org-{suffix}")
        user = AppUser(email=f"mgr-{suffix}@example.com", name="Manager")
        db.add_all([organization, user])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=user.id, role="manager"),
            ApiCredential(
                organization_id=organization.id,
                user_id=user.id,
                name="Manager key",
                key_prefix=key[:18],
                key_hash=_hash_key(key),
            ),
        ])
        db.commit()
        return key, organization.id
    finally:
        db.close()


def _property(organization_id, state="DC", city="Washington", address="1600 Pennsylvania Ave NW", zip_code="20500"):
    db = SessionLocal()
    try:
        lead = Lead(seller_name="Record Under Review", phone="+15555550000")
        db.add(lead)
        db.flush()
        row = Property(lead_id=lead.id, address=address, city=city, state=state, zip_code=zip_code)
        db.add(row)
        db.flush()
        # Tenancy lives in WorkspaceEntity, mirroring how acquisition intake
        # creates properties.
        db.add(WorkspaceEntity(organization_id=organization_id, entity_type="property", entity_id=row.id))
        db.commit()
        return row.id
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_contract_publishes_the_write_boundary():
    key, _ = _manager_workspace()
    response = client.get("/verified-ingest/contract", headers=_auth(key))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verification_status_written"] == "verified"
    assert "county_fips" in body["writable_fields"]
    for field in ("owner_name", "phone", "arv", "tax_delinquency"):
        assert field in body["never_established_by_this_source"]
        assert field not in body["writable_fields"]


def test_preview_reports_facts_without_writing(monkeypatch):
    _patch_census(monkeypatch)
    key, organization_id = _manager_workspace()
    property_id = _property(organization_id)

    response = client.post("/verified-ingest/preview", headers=_auth(key), json={"property_ids": [property_id]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["committed"] is False
    result = body["results"][0]
    assert result["status"] == "resolved"
    assert result["facts"]["county_geoid"] == "11001"
    assert result["facts"]["census_tract_geoid"] == "11001006202"

    db = SessionLocal()
    try:
        written = db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()
        assert written == [], "preview must not write facts"
    finally:
        db.close()


def test_commit_writes_verified_geography_facts(monkeypatch):
    _patch_census(monkeypatch)
    key, organization_id = _manager_workspace()
    property_id = _property(organization_id)

    response = client.post("/verified-ingest/commit", headers=_auth(key), json={"property_ids": [property_id]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["committed"] is True
    result = body["results"][0]
    assert result["status"] == "written"
    assert result["facts_written"] > 0

    db = SessionLocal()
    try:
        rows = db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()
        by_field = {row.field_name: row for row in rows}
        assert by_field["county_geoid"].value_json["value"] == "11001"
        assert by_field["county_geoid"].verification_status == "verified"
        assert by_field["county_geoid"].source == "census_geocoder"
        assert by_field["county_geoid"].confidence == pytest.approx(92.0)
        # Provenance must be recorded, not implied.
        assert by_field["county_geoid"].source_reference
        assert by_field["county_geoid"].observed_at is not None
    finally:
        db.close()


def test_fields_the_source_cannot_establish_are_never_written(monkeypatch):
    """The allowlist holds even when the provider volunteers extra fields.

    A future provider change (or a compromised upstream) must not be able to
    introduce ownership or contact data through this path.
    """
    hostile = {
        "result": {
            "addressMatches": [{
                **GEOCODER_FIXTURE["result"]["addressMatches"][0],
                "owner_name": "Somebody Not Verified",
                "phone": "+15555551234",
                "arv": 425000,
                "tax_delinquency": True,
            }]
        }
    }
    _patch_census(monkeypatch, geocoder=hostile)
    key, organization_id = _manager_workspace()
    property_id = _property(organization_id)

    response = client.post("/verified-ingest/commit", headers=_auth(key), json={"property_ids": [property_id]})
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        rows = db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()
        stored = {row.field_name for row in rows}
        for field in ("owner_name", "phone", "arv", "tax_delinquency"):
            assert field not in stored, f"{field} must never be written by this source"
        assert "county_geoid" in stored
    finally:
        db.close()


def test_texas_property_is_rejected_and_writes_nothing(monkeypatch):
    _patch_census(monkeypatch)
    key, organization_id = _manager_workspace()
    property_id = _property(organization_id, state="TX", city="Houston", address="123 Main St", zip_code="77002")

    response = client.post("/verified-ingest/commit", headers=_auth(key), json={"property_ids": [property_id]})
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["status"] == "rejected"
    assert "Texas" in result["reason"]

    db = SessionLocal()
    try:
        rows = db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()
        assert rows == []
    finally:
        db.close()


def test_a_rejection_does_not_abort_the_rest_of_the_batch(monkeypatch):
    _patch_census(monkeypatch)
    key, organization_id = _manager_workspace()
    texas_id = _property(organization_id, state="TX", city="Dallas", address="456 Oak St", zip_code="75201")
    valid_id = _property(organization_id)

    response = client.post(
        "/verified-ingest/commit",
        headers=_auth(key),
        json={"property_ids": [texas_id, valid_id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    statuses = {item["property_id"]: item["status"] for item in body["results"]}
    assert statuses[texas_id] == "rejected"
    assert statuses[valid_id] == "written"
    assert body["summary"]["rejected"] == 1


def test_commit_requires_manager_role(monkeypatch):
    _patch_census(monkeypatch)
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"Viewer Org {suffix}", slug=f"viewer-org-{suffix}")
        user = AppUser(email=f"viewer-{suffix}@example.com", name="Viewer")
        db.add_all([organization, user])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=user.id, role="viewer"),
            ApiCredential(
                organization_id=organization.id, user_id=user.id, name="Viewer key",
                key_prefix=key[:18], key_hash=_hash_key(key),
            ),
        ])
        db.commit()
        viewer_org_id = organization.id
    finally:
        db.close()

    property_id = _property(viewer_org_id)
    response = client.post("/verified-ingest/commit", headers=_auth(key), json={"property_ids": [property_id]})
    assert response.status_code == 403, response.text


def test_another_workspace_property_cannot_be_enriched(monkeypatch):
    """Tenancy is enforced through WorkspaceEntity, not by property id alone."""
    _patch_census(monkeypatch)
    _, other_org = _manager_workspace()
    foreign_id = _property(other_org)
    key, _ = _manager_workspace()

    response = client.post("/verified-ingest/preview", headers=_auth(key), json={"property_ids": [foreign_id]})
    assert response.status_code == 404, response.text

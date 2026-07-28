"""County distress ingest.

The upstream payloads below are TEST FIXTURES shaped like real Socrata and
ArcGIS responses. The addresses are synthetic and must never be loaded into an
application database as if they were public records.
"""

import json
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.index import app
from app import distress_ingest, security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization, WorkspaceEntity
from app.database import SessionLocal
from app.intelligence_models import IntelligenceFact
from app.models import Lead, Property

client = TestClient(app)

MANAGED_ENV = [distress_ingest.JURISDICTIONS_INLINE_ENV, distress_ingest.JURISDICTIONS_FILE_ENV]

SOCRATA_JURISDICTION = {
    "id": "example-county-tax",
    "state": "FL",
    "county": "Example County",
    "category": "tax_delinquency",
    "transport": "socrata",
    "endpoint": "https://data.example-county.gov/resource/aaaa-1111.json",
    "address_field": "situs_address",
    "zip_field": "situs_zip",
    "field_map": {
        "tax_delinquent": "is_delinquent",
        "tax_delinquent_years": "years_delinquent",
        "tax_amount_due": "amount_due",
    },
}


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()
    for name in MANAGED_ENV:
        os.environ.pop(name, None)


teardown_function = setup_function


def _configure(entries):
    os.environ[distress_ingest.JURISDICTIONS_INLINE_ENV] = json.dumps({"jurisdictions": entries})


def _workspace(role="manager"):
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"DI Org {suffix}", slug=f"di-org-{suffix}")
        user = AppUser(email=f"di-{suffix}@example.com", name="Ops")
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


def _property(organization_id, address, zip_code, state="FL", city="Pensacola"):
    db = SessionLocal()
    try:
        lead = Lead(seller_name="Under Review", phone="+15555550000")
        db.add(lead)
        db.flush()
        row = Property(lead_id=lead.id, address=address, city=city, state=state, zip_code=zip_code)
        db.add(row)
        db.flush()
        db.add(WorkspaceEntity(organization_id=organization_id, entity_type="property", entity_id=row.id))
        db.commit()
        return row.id
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def _patch_rows(monkeypatch, rows):
    async def fake_fetch_page(source, limit, offset):
        return rows[offset:offset + limit]
    monkeypatch.setattr(distress_ingest, "fetch_page", fake_fetch_page)


# ------------------------------------------------------------ configuration --

def test_registry_is_empty_until_a_jurisdiction_is_configured():
    key, _ = _workspace()
    body = client.get("/distress-ingest/jurisdictions", headers=_auth(key)).json()
    assert body["configured"] == 0
    assert body["html_scraping_supported"] is False
    assert "Add a jurisdiction" in body["next_step"]


def test_configured_jurisdiction_is_listed():
    _configure([SOCRATA_JURISDICTION])
    key, _ = _workspace()
    body = client.get("/distress-ingest/jurisdictions", headers=_auth(key)).json()
    assert body["configured"] == 1
    entry = body["jurisdictions"][0]
    assert entry["county"] == "Example County"
    assert entry["verification_status"] == "verified"


def test_a_jurisdiction_cannot_map_fields_its_category_may_not_write():
    """Config must not be able to widen a category's write boundary."""
    hostile = {**SOCRATA_JURISDICTION, "field_map": {**SOCRATA_JURISDICTION["field_map"], "owner_name": "owner"}}
    _configure([hostile])
    key, _ = _workspace()
    response = client.get("/distress-ingest/jurisdictions", headers=_auth(key))
    assert response.status_code == 422
    assert "owner_name" in response.text


def test_scraping_transport_is_rejected():
    _configure([{**SOCRATA_JURISDICTION, "transport": "html_scrape"}])
    key, _ = _workspace()
    response = client.get("/distress-ingest/jurisdictions", headers=_auth(key))
    assert response.status_code == 422
    assert "HTML scraping is not supported" in response.text


def test_excluded_state_jurisdiction_is_rejected():
    _configure([{**SOCRATA_JURISDICTION, "state": "TX", "county": "Harris County"}])
    key, _ = _workspace()
    response = client.get("/distress-ingest/jurisdictions", headers=_auth(key))
    assert response.status_code == 409


def test_licensed_category_cannot_be_configured_as_a_county_dataset():
    _configure([{**SOCRATA_JURISDICTION, "category": "fsbo_listing", "field_map": {"fsbo_listed": "listed"}}])
    key, _ = _workspace()
    response = client.get("/distress-ingest/jurisdictions", headers=_auth(key))
    assert response.status_code == 422
    assert "licensed" in response.text.lower()


# --------------------------------------------------------------- validation --

def test_validate_reports_missing_mapped_columns(monkeypatch):
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [{"situs_address": "111 Palafox St", "situs_zip": "32501", "is_delinquent": True}])
    key, _ = _workspace()
    body = client.post("/distress-ingest/validate", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-tax"}).json()
    assert body["valid"] is False
    assert "tax_amount_due" in body["missing_mapped_columns"]


def test_validate_passes_when_schema_matches(monkeypatch):
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [{
        "situs_address": "111 Palafox St", "situs_zip": "32501",
        "is_delinquent": True, "years_delinquent": 2, "amount_due": 4210.55,
    }])
    key, _ = _workspace()
    body = client.post("/distress-ingest/validate", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-tax"}).json()
    assert body["valid"] is True
    assert body["address_field_present"] is True


# ------------------------------------------------------------------- ingest --

def test_preview_matches_rows_without_writing(monkeypatch):
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [{
        "situs_address": "111 Palafox St", "situs_zip": "32501",
        "is_delinquent": True, "years_delinquent": 2, "amount_due": 4210.55,
    }])
    key, organization_id = _workspace()
    property_id = _property(organization_id, "111 Palafox St", "32501")

    body = client.post("/distress-ingest/preview", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-tax"}).json()
    assert body["dry_run"] is True
    assert body["summary"]["matched"] == 1
    assert body["matches"][0]["property_id"] == property_id

    db = SessionLocal()
    try:
        assert db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all() == []
    finally:
        db.close()


def test_commit_writes_distress_facts_with_jurisdiction_provenance(monkeypatch):
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [{
        "situs_address": "222 Garden St", "situs_zip": "32502",
        "is_delinquent": True, "years_delinquent": 3, "amount_due": 8100.0,
    }])
    key, organization_id = _workspace()
    property_id = _property(organization_id, "222 Garden St", "32502")

    body = client.post("/distress-ingest/commit", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-tax"}).json()
    assert body["committed"] is True
    assert body["summary"]["facts_written"] == 3

    db = SessionLocal()
    try:
        rows = db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()
        by_field = {row.field_name: row for row in rows}
        assert by_field["tax_delinquent_years"].value_json["value"] == 3
        assert by_field["tax_delinquent"].verification_status == "verified"
        assert by_field["tax_delinquent"].source == "tax_delinquency"
        assert by_field["tax_delinquent"].confidence == pytest.approx(90.0)
        assert "Example County" in by_field["tax_delinquent"].source_reference
    finally:
        db.close()


def test_unmapped_upstream_columns_are_never_written(monkeypatch):
    """An upstream schema change adding owner data must not leak through."""
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [{
        "situs_address": "333 Wright St", "situs_zip": "32503",
        "is_delinquent": True, "years_delinquent": 1, "amount_due": 900.0,
        "owner_name": "Not Verified Person", "owner_phone": "+15555559999",
    }])
    key, organization_id = _workspace()
    property_id = _property(organization_id, "333 Wright St", "32503")
    client.post("/distress-ingest/commit", headers=_auth(key), json={"jurisdiction_id": "example-county-tax"})

    db = SessionLocal()
    try:
        stored = {row.field_name for row in db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()}
        assert "owner_name" not in stored
        assert "owner_phone" not in stored
        assert "tax_delinquent" in stored
    finally:
        db.close()


def test_rows_that_match_no_property_are_counted_not_invented(monkeypatch):
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [{
        "situs_address": "999 Nowhere Rd", "situs_zip": "32599",
        "is_delinquent": True, "years_delinquent": 1, "amount_due": 10.0,
    }])
    key, _ = _workspace()
    body = client.post("/distress-ingest/preview", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-tax"}).json()
    assert body["summary"]["matched"] == 0
    assert body["summary"]["unmatched_rows"] == 1


def test_commit_requires_manager_role(monkeypatch):
    _configure([SOCRATA_JURISDICTION])
    _patch_rows(monkeypatch, [])
    key, _ = _workspace(role="viewer")
    response = client.post("/distress-ingest/commit", headers=_auth(key),
                           json={"jurisdiction_id": "example-county-tax"})
    assert response.status_code == 403


def test_arcgis_rows_are_unwrapped_from_features(monkeypatch):
    arcgis = {
        **SOCRATA_JURISDICTION,
        "id": "example-county-code",
        "category": "code_violation",
        "transport": "arcgis",
        "endpoint": "https://gis.example-county.gov/arcgis/rest/services/Code/FeatureServer/0/query",
        "field_map": {"code_violation_open": "case_open", "code_violation_count": "case_count"},
    }
    _configure([arcgis])

    captured = {}

    async def fake_client_get(self, url, params=None, headers=None):
        captured["params"] = params

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"features": [{"attributes": {
                    "situs_address": "444 Cervantes St", "situs_zip": "32504",
                    "case_open": True, "case_count": 2,
                }}]}

        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_client_get)
    key, organization_id = _workspace()
    property_id = _property(organization_id, "444 Cervantes St", "32504")
    body = client.post("/distress-ingest/commit", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-code"}).json()
    assert body["summary"]["facts_written"] == 2
    assert captured["params"]["f"] == "json"

    db = SessionLocal()
    try:
        stored = {row.field_name for row in db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_id == property_id,
        )).all()}
        assert stored == {"code_violation_open", "code_violation_count"}
    finally:
        db.close()


def test_another_workspace_property_is_never_matched(monkeypatch):
    """Properties carry no organization column; tenancy lives in
    WorkspaceEntity. An unscoped index would let one workspace's ingest write
    facts onto another workspace's records."""
    _configure([SOCRATA_JURISDICTION])
    _, other_org = _workspace()
    foreign_id = _property(other_org, "555 Barrancas Ave", "32505")
    _patch_rows(monkeypatch, [{
        "situs_address": "555 Barrancas Ave", "situs_zip": "32505",
        "is_delinquent": True, "years_delinquent": 4, "amount_due": 1200.0,
    }])
    key, organization_id = _workspace()

    body = client.post("/distress-ingest/commit", headers=_auth(key),
                       json={"jurisdiction_id": "example-county-tax"}).json()
    assert body["summary"]["properties_touched"] == 0
    assert body["summary"]["unmatched_rows"] == 1

    db = SessionLocal()
    try:
        assert db.scalars(select(IntelligenceFact).where(
            IntelligenceFact.entity_id == foreign_id,
            IntelligenceFact.organization_id == organization_id,
        )).all() == []
    finally:
        db.close()

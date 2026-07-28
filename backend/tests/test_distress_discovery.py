"""Nationwide discovery sweep.

Catalog payloads below are TEST FIXTURES shaped like the real Socrata and
ArcGIS catalog responses.
"""

import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient

from api.index import app
from app import distress_discovery, security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization
from app.database import SessionLocal

client = TestClient(app)


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()


def _workspace():
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"Disc Org {suffix}", slug=f"disc-org-{suffix}")
        user = AppUser(email=f"disc-{suffix}@example.com", name="Ops")
        db.add_all([organization, user])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=user.id, role="manager"),
            ApiCredential(organization_id=organization.id, user_id=user.id, name="key",
                          key_prefix=key[:18], key_hash=_hash_key(key)),
        ])
        db.commit()
        return key
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


SOCRATA_CATALOG = {
    "results": [{
        "resource": {"id": "abcd-1234", "name": "Escambia County Delinquent Tax Roll",
                     "description": "Parcels with unpaid property tax."},
        "metadata": {"domain": "data.escambia-fl.gov"},
        "permalink": "https://data.escambia-fl.gov/d/abcd-1234",
    }]
}

ARCGIS_CATALOG = {
    "results": [{
        "id": "arc-1", "title": "Code Enforcement Cases", "owner": "cityofpensacola",
        "snippet": "Open code enforcement cases in Florida.",
        "url": "https://services.arcgis.com/xyz/arcgis/rest/services/Code/FeatureServer",
    }]
}


def _patch_catalogs(monkeypatch, socrata=SOCRATA_CATALOG, arcgis=ARCGIS_CATALOG):
    async def fake_get_json(url, params):
        return socrata if url == distress_discovery.SOCRATA_CATALOG_URL else arcgis
    monkeypatch.setattr(distress_discovery, "_get_json", fake_get_json)


def test_categories_document_the_nationwide_catalogs():
    body = client.get("/distress-discovery/categories", headers=_auth(_workspace())).json()
    ids = {item["id"] for item in body["categories"]}
    assert {"tax_delinquency", "code_violation", "foreclosure_sale"} <= ids
    assert {item["id"] for item in body["catalogs"]} == {"socrata", "arcgis"}
    assert "No single nationwide distress dataset exists" in body["note"]


def test_sweep_returns_candidates_without_enabling_anything(monkeypatch):
    _patch_catalogs(monkeypatch)
    body = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                       json={"categories": ["tax_delinquency"]}).json()
    assert body["enabled_anything"] is False
    assert body["committed"] is False
    candidates = body["candidates"]["tax_delinquency"]
    assert candidates, "sweep should surface candidates"
    for candidate in candidates:
        assert candidate["status"] == "unvalidated"


def test_socrata_candidate_builds_a_resource_endpoint(monkeypatch):
    _patch_catalogs(monkeypatch, arcgis={"results": []})
    body = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                       json={"categories": ["tax_delinquency"], "catalogs": ["socrata"]}).json()
    candidate = body["candidates"]["tax_delinquency"][0]
    assert candidate["endpoint"] == "https://data.escambia-fl.gov/resource/abcd-1234.json"
    assert candidate["transport"] == "socrata"


def test_arcgis_candidate_builds_a_query_endpoint(monkeypatch):
    _patch_catalogs(monkeypatch, socrata={"results": []})
    body = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                       json={"categories": ["code_violation"], "catalogs": ["arcgis"]}).json()
    candidate = body["candidates"]["code_violation"][0]
    assert candidate["endpoint"].endswith("/FeatureServer/0/query")
    assert candidate["transport"] == "arcgis"


def test_suggested_entry_only_offers_fields_the_category_may_write(monkeypatch):
    _patch_catalogs(monkeypatch, arcgis={"results": []})
    body = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                       json={"categories": ["tax_delinquency"], "catalogs": ["socrata"]}).json()
    suggested = body["candidates"]["tax_delinquency"][0]["suggested_registry_entry"]
    assert set(suggested["field_map"]) <= set(distress_discovery.PROVIDERS_BY_ID["tax_delinquency"].writable_fields)
    assert "owner_name" not in suggested["field_map"]


def test_excluded_state_filter_is_dropped_and_reported(monkeypatch):
    _patch_catalogs(monkeypatch)
    body = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                       json={"categories": ["tax_delinquency"], "states": ["TX", "FL"]}).json()
    assert body["excluded_states_ignored"] == ["TX"]
    assert body["states_filter"] == ["FL"]


def test_catalog_failure_is_reported_not_fatal(monkeypatch):
    import httpx

    async def failing(url, params):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(distress_discovery, "_get_json", failing)
    body = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                       json={"categories": ["tax_delinquency"]}).json()
    assert body["summary"]["total_candidates"] == 0
    assert body["summary"]["catalog_errors"] > 0


def test_unknown_category_is_rejected():
    response = client.post("/distress-discovery/sweep", headers=_auth(_workspace()),
                           json={"categories": ["not_a_category"]})
    assert response.status_code == 422

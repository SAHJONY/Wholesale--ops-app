import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient

from api.index import app
from app import getting_started, security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization, WorkspaceEntity
from app.database import SessionLocal
from app.models import Buyer, Lead, Property

client = TestClient(app)


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()


def _workspace():
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        org = Organization(name=f"GS Org {suffix}", slug=f"gs-org-{suffix}")
        user = AppUser(email=f"gs-{suffix}@example.com", name="Ops")
        db.add_all([org, user]); db.flush()
        db.add_all([
            Membership(organization_id=org.id, user_id=user.id, role="manager"),
            ApiCredential(organization_id=org.id, user_id=user.id, name="key",
                          key_prefix=key[:18], key_hash=_hash_key(key)),
        ])
        db.commit()
        return key, org.id
    finally:
        db.close()


def _buyer(org_id, zips=("32501",)):
    db = SessionLocal()
    try:
        b = Buyer(name="Buyer", phone="+15555550001", zip_codes=list(zips))
        db.add(b); db.flush()
        db.add(WorkspaceEntity(organization_id=org_id, entity_type="buyer", entity_id=b.id))
        db.commit()
    finally:
        db.close()


def _property(org_id):
    db = SessionLocal()
    try:
        lead = Lead(seller_name="Seller", phone="+15555550000")
        db.add(lead); db.flush()
        p = Property(lead_id=lead.id, address=f"{uuid.uuid4().hex[:5]} Main St",
                     city="Pensacola", state="FL", zip_code="32501")
        db.add(p); db.flush()
        db.add(WorkspaceEntity(organization_id=org_id, entity_type="property", entity_id=p.id))
        db.commit()
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def _steps(key):
    body = client.get("/getting-started/next-steps", headers=_auth(key)).json()
    return body, {s["id"]: s for s in body["steps"]}


def test_empty_workspace_points_at_the_buyer_network_first():
    """Buyer depth gates assignment, so it must lead the sequence."""
    key, _ = _workspace()
    body, steps = _steps(key)
    assert body["next"]["id"] == "buyers"
    assert steps["buyers"]["status"] == "todo"


def test_steps_whose_prerequisite_is_unmet_are_blocked_not_offered():
    """Configuring a county feed with no properties writes nothing; offering it
    as an equal option wastes the operator's time."""
    key, _ = _workspace()
    _, steps = _steps(key)
    assert steps["verify"]["status"] == "blocked"
    assert steps["jurisdictions"]["status"] == "blocked"
    assert "properties first" in steps["verify"]["blocked_by"]


def test_adding_buyers_unblocks_market_ranking_and_advances_next():
    key, org = _workspace()
    _buyer(org)
    body, steps = _steps(key)
    assert steps["buyers"]["status"] == "done"
    assert body["next"]["id"] != "buyers"


def test_adding_properties_unblocks_verification_and_jurisdictions():
    key, org = _workspace()
    _property(org)
    _, steps = _steps(key)
    assert steps["properties"]["status"] == "done"
    assert steps["verify"]["status"] == "todo"
    assert steps["jurisdictions"]["status"] == "todo"


def test_unverified_properties_keep_verification_outstanding():
    key, org = _workspace()
    _property(org)
    _, steps = _steps(key)
    assert steps["verify"]["status"] == "todo"
    assert "0 of 1 verified" in steps["verify"]["detail"]


def test_progress_is_reported_as_a_fraction_of_the_sequence():
    key, org = _workspace()
    _buyer(org)
    _property(org)
    body, _ = _steps(key)
    assert body["summary"]["total_steps"] == 6
    assert body["summary"]["done"] >= 2
    assert 0 < body["summary"]["percent_complete"] < 100


def test_missing_credentials_are_named_rather_than_counted():
    key, _ = _workspace()
    _, steps = _steps(key)
    assert steps["credentials"]["status"] == "todo"
    assert "Outstanding:" in steps["credentials"]["detail"]


def test_a_malformed_jurisdiction_registry_does_not_break_the_guide():
    """The guide must survive bad configuration; it is the page an operator
    reaches for when something is wrong."""
    os.environ[getting_started.load_jurisdictions.__module__.split('.')[0] and "DISTRESS_JURISDICTIONS"] = "{not json"
    try:
        key, _ = _workspace()
        response = client.get("/getting-started/next-steps", headers=_auth(key))
        assert response.status_code == 200, response.text
        steps = {s["id"]: s for s in response.json()["steps"]}
        assert "Registry error" in steps["jurisdictions"]["detail"]
    finally:
        os.environ.pop("DISTRESS_JURISDICTIONS", None)

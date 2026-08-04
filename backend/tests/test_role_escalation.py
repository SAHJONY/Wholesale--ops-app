import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient

from api.index import app
from app import security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization
from app.database import SessionLocal

client = TestClient(app)


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()


def _workspace_with_admin():
    """Create an organization holding an owner and an admin, and return an API
    key authenticating as the admin."""
    suffix = uuid.uuid4().hex[:10]
    admin_key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"Esc Org {suffix}", slug=f"esc-org-{suffix}")
        owner = AppUser(email=f"owner-{suffix}@example.com", name="Owner")
        admin = AppUser(email=f"admin-{suffix}@example.com", name="Admin")
        db.add_all([organization, owner, admin])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=owner.id, role="owner"),
            Membership(organization_id=organization.id, user_id=admin.id, role="admin"),
            ApiCredential(
                organization_id=organization.id,
                user_id=admin.id,
                name="Admin key",
                key_prefix=admin_key[:18],
                key_hash=_hash_key(admin_key),
            ),
        ])
        db.commit()
        return admin_key, owner.email, owner.id, admin.email
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_admin_cannot_grant_owner_role():
    admin_key, _, _, _ = _workspace_with_admin()
    response = client.post(
        "/auth/team",
        headers=_auth(admin_key),
        json={"email": f"new-{uuid.uuid4().hex[:8]}@example.com", "role": "owner"},
    )
    assert response.status_code == 403, response.text


def test_admin_cannot_self_escalate_to_owner():
    admin_key, _, _, admin_email = _workspace_with_admin()
    response = client.post(
        "/auth/team",
        headers=_auth(admin_key),
        json={"email": admin_email, "role": "owner"},
    )
    assert response.status_code == 403, response.text


def test_admin_cannot_demote_the_owner():
    admin_key, owner_email, _, _ = _workspace_with_admin()
    response = client.post(
        "/auth/team",
        headers=_auth(admin_key),
        json={"email": owner_email, "role": "viewer"},
    )
    assert response.status_code == 403, response.text


def test_admin_cannot_mint_an_api_key_for_the_owner():
    admin_key, _, owner_id, _ = _workspace_with_admin()
    response = client.post(
        "/auth/api-keys",
        headers=_auth(admin_key),
        json={"user_id": owner_id, "name": "borrowed"},
    )
    assert response.status_code == 403, response.text


def test_admin_can_still_manage_roles_at_or_below_its_own():
    admin_key, _, _, _ = _workspace_with_admin()
    response = client.post(
        "/auth/team",
        headers=_auth(admin_key),
        json={"email": f"analyst-{uuid.uuid4().hex[:8]}@example.com", "role": "acquisitions"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "acquisitions"

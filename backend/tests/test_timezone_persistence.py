import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.index import app
from app import security_middleware
from app.auth import HUMAN_SESSION_NAME, _hash_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization, UserPassword
from app.database import SessionLocal

client = TestClient(app)


def setup_function():
    # The shared rate-limit buckets are process-global; clear them so unrelated
    # tests cannot push these requests over the auth-path limit.
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()


def _seed_owner_with_session():
    """Create an owner plus a human-login credential, then forget the ORM identity map.

    Reading the rows back through a *new* session is what a subsequent HTTP
    request does, and it is the only way to observe what the database actually
    returns.
    """
    suffix = uuid.uuid4().hex[:10]
    token = f"sahjony_live_{suffix}"
    db = SessionLocal()
    try:
        organization = Organization(name=f"TZ Org {suffix}", slug=f"tz-org-{suffix}")
        user = AppUser(email=f"tz-{suffix}@example.com", name="TZ Owner")
        db.add_all([organization, user])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=user.id, role="owner"),
            ApiCredential(
                organization_id=organization.id,
                user_id=user.id,
                name=HUMAN_SESSION_NAME,
                key_prefix=token[:18],
                key_hash=_hash_key(token),
            ),
            UserPassword(
                user_id=user.id,
                password_hash="scrypt$00$00",
                locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
            ),
        ])
        db.commit()
        return token, user.id, user.email
    finally:
        db.close()


def test_timestamps_read_back_timezone_aware():
    _, user_id, _ = _seed_owner_with_session()
    db = SessionLocal()
    try:
        password = db.scalar(select(UserPassword).where(UserPassword.user_id == user_id))
        credential = db.scalar(select(ApiCredential).where(ApiCredential.user_id == user_id))
        assert password.locked_until.tzinfo is not None
        assert credential.created_at.tzinfo is not None
        # The comparisons the auth paths perform must not raise TypeError.
        now = datetime.now(timezone.utc)
        assert isinstance(now - credential.created_at, timedelta)
        assert password.locked_until > now
    finally:
        db.close()


def test_authenticated_request_survives_session_lifetime_check():
    """Regression: the human-session age check compared aware `now` to a naive
    column value, so every request after login returned 500."""
    token, _, email = _seed_owner_with_session()
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == email


def test_locked_account_reports_lockout_instead_of_crashing():
    """Regression: a set `locked_until` made every later login raise TypeError,
    permanently bricking the account instead of returning 429."""
    _, _, email = _seed_owner_with_session()
    response = client.post(
        "/human-auth/login",
        json={"email": email, "password": "not-the-real-password"},
    )
    assert response.status_code == 429, response.text

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import ApiCredential, AppUser, CrmActivity, Membership, Organization, UserPassword
from .database import get_db

router = APIRouter(prefix="/human-auth", tags=["human-authentication"])


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_session_token() -> str:
    return f"sahjony_live_{secrets.token_urlsafe(32)}"


def _hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, expected_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = _hash_password(password, bytes.fromhex(salt_hex)).split("$", 2)[2]
        return hmac.compare_digest(actual, expected_hex)
    except Exception:
        return False


def _valid_recovery_secret(provided: str | None) -> bool:
    configured = os.getenv("BOOTSTRAP_SECRET")
    return bool(configured and provided and secrets.compare_digest(configured, provided))


def _find_owner(db: Session, email: str | None = None):
    query = (
        select(Membership, AppUser, Organization)
        .join(AppUser, AppUser.id == Membership.user_id)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(
            Membership.role == "owner",
            AppUser.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )
    if email:
        query = query.where(AppUser.email == email)
    rows = db.execute(query).all()
    if len(rows) != 1:
        raise HTTPException(404, "Unique active owner workspace not found")
    return rows[0]


@router.post("/set-password")
def set_password(
    payload: dict,
    x_bootstrap_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not _valid_recovery_secret(x_bootstrap_secret):
        raise HTTPException(403, "Invalid recovery secret")

    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    if email and "@" not in email:
        raise HTTPException(422, "Valid email is required")
    if len(password) < 12:
        raise HTTPException(422, "Password must contain at least 12 characters")

    membership, user, organization = _find_owner(db, email or None)
    record = db.scalar(select(UserPassword).where(UserPassword.user_id == user.id))
    if record:
        record.password_hash = _hash_password(password)
        record.failed_attempts = 0
        record.locked_until = None
    else:
        record = UserPassword(user_id=user.id, password_hash=_hash_password(password))
        db.add(record)

    db.add(CrmActivity(
        organization_id=organization.id,
        user_id=user.id,
        activity_type="human_password_set",
        summary="Owner human-login password was created or reset",
        metadata_json={"email": user.email},
    ))
    db.commit()
    return {
        "configured": True,
        "email": user.email,
        "organization": organization.name,
        "message": "Password configured. You can now sign in from any device.",
    }


@router.post("/login")
def login(payload: dict, db: Session = Depends(get_db)):
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    if "@" not in email or not password:
        raise HTTPException(422, "Email and password are required")

    user = db.scalar(select(AppUser).where(AppUser.email == email, AppUser.is_active.is_(True)))
    if not user:
        raise HTTPException(401, "Invalid email or password")

    record = db.scalar(select(UserPassword).where(UserPassword.user_id == user.id))
    now = datetime.utcnow()
    if not record:
        raise HTTPException(401, "Password login is not configured for this account")
    if record.locked_until and record.locked_until > now:
        raise HTTPException(429, "Account temporarily locked. Try again later.")
    if not _verify_password(password, record.password_hash):
        record.failed_attempts += 1
        if record.failed_attempts >= 5:
            record.locked_until = now + timedelta(minutes=15)
            record.failed_attempts = 0
        db.commit()
        raise HTTPException(401, "Invalid email or password")

    membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
    if not membership:
        raise HTTPException(403, "No active workspace membership")
    organization = db.get(Organization, membership.organization_id)
    if not organization or not organization.is_active:
        raise HTTPException(403, "Workspace access disabled")

    record.failed_attempts = 0
    record.locked_until = None

    old_sessions = db.scalars(select(ApiCredential).where(
        ApiCredential.organization_id == organization.id,
        ApiCredential.user_id == user.id,
        ApiCredential.name == "Human login session",
        ApiCredential.revoked_at.is_(None),
    )).all()
    for session in old_sessions:
        session.revoked_at = now

    raw_token = _new_session_token()
    credential = ApiCredential(
        organization_id=organization.id,
        user_id=user.id,
        name="Human login session",
        key_prefix=raw_token[:18],
        key_hash=_hash_key(raw_token),
    )
    db.add_all([
        credential,
        CrmActivity(
            organization_id=organization.id,
            user_id=user.id,
            activity_type="human_login",
            summary="User signed in with email and password",
            metadata_json={"email": user.email},
        ),
    ])
    db.commit()
    return {
        "access_token": raw_token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "name": user.name, "role": membership.role},
        "organization": {"id": organization.id, "name": organization.name, "slug": organization.slug},
    }


@router.post("/logout")
def logout(payload: dict, db: Session = Depends(get_db)):
    token = str(payload.get("token") or "").strip()
    if not token:
        return {"logged_out": True}
    credential = db.scalar(select(ApiCredential).where(
        ApiCredential.key_hash == _hash_key(token),
        ApiCredential.revoked_at.is_(None),
    ))
    if credential and credential.name == "Human login session":
        credential.revoked_at = datetime.utcnow()
        db.commit()
    return {"logged_out": True}

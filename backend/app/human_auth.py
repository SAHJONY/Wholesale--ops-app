import hashlib
import hmac
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import (
    ApiCredential,
    AppUser,
    CrmActivity,
    Membership,
    Organization,
    PasswordResetCode,
    UserPassword,
)
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


def _email_html(code: str) -> str:
    return (
        "<div style='font-family:Arial,sans-serif'>"
        "<h2>SAHJONY Wholesale OS</h2>"
        f"<p>Your password reset code is <strong style='font-size:24px'>{code}</strong>.</p>"
        "<p>This code expires in 10 minutes. If you did not request it, ignore this email.</p>"
        "</div>"
    )


def _send_with_smtp(email: str, code: str) -> bool:
    username = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASS") or "").strip()
    if not username or not password:
        return False

    host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT") or "587")
    sender = (os.getenv("AUTH_FROM_EMAIL") or username).strip()

    message = EmailMessage()
    message["Subject"] = "Your SAHJONY password reset code"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        f"Your SAHJONY Wholesale OS password reset code is {code}. "
        "This code expires in 10 minutes."
    )
    message.add_alternative(_email_html(code), subtype="html")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.send_message(message)
    return True


def _send_with_resend(email: str, code: str) -> bool:
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key:
        return False
    from_email = os.getenv("AUTH_FROM_EMAIL", "SAHJONY Wholesale OS <onboarding@resend.dev>")
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": from_email,
            "to": [email],
            "subject": "Your SAHJONY password reset code",
            "html": _email_html(code),
        },
        timeout=15,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Resend rejected email with status {response.status_code}")
    return True


def _send_reset_email(email: str, code: str) -> None:
    errors: list[str] = []

    try:
        if _send_with_smtp(email, code):
            return
    except Exception as exc:
        errors.append(f"smtp:{type(exc).__name__}")

    try:
        if _send_with_resend(email, code):
            return
    except Exception as exc:
        errors.append(f"resend:{type(exc).__name__}")

    smtp_configured = bool((os.getenv("SMTP_USER") or "").strip() and (os.getenv("SMTP_PASS") or "").strip())
    resend_configured = bool((os.getenv("RESEND_API_KEY") or "").strip())
    if not smtp_configured and not resend_configured:
        raise HTTPException(503, "Password-reset email is not configured yet")
    raise HTTPException(502, "Unable to send password-reset email")


@router.post("/set-password")
def set_password(
    payload: dict,
    x_bootstrap_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not _valid_recovery_secret(x_bootstrap_secret):
        raise HTTPException(403, "Invalid recovery secret")

    email = str(payload.get("email") or payload.get("owner_email") or "").strip().lower()
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


@router.post("/request-password-reset")
def request_password_reset(payload: dict, db: Session = Depends(get_db)):
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email:
        raise HTTPException(422, "Valid email is required")

    user = db.scalar(select(AppUser).where(AppUser.email == email, AppUser.is_active.is_(True)))
    if not user:
        return {"accepted": True, "message": "If that account exists, a reset code was sent."}

    now = datetime.now(timezone.utc)
    existing = db.scalars(select(PasswordResetCode).where(
        PasswordResetCode.user_id == user.id,
        PasswordResetCode.used_at.is_(None),
    )).all()
    for item in existing:
        item.used_at = now

    code = f"{secrets.randbelow(1_000_000):06d}"
    reset = PasswordResetCode(
        user_id=user.id,
        code_hash=_hash_key(code),
        expires_at=now + timedelta(minutes=10),
    )
    db.add(reset)
    db.flush()
    try:
        _send_reset_email(user.email, code)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return {"accepted": True, "message": "If that account exists, a reset code was sent."}


@router.post("/reset-password")
def reset_password(payload: dict, db: Session = Depends(get_db)):
    email = str(payload.get("email") or "").strip().lower()
    code = str(payload.get("code") or "").strip()
    password = str(payload.get("password") or "")
    if "@" not in email or len(code) != 6 or not code.isdigit():
        raise HTTPException(422, "Email and a valid 6-digit code are required")
    if len(password) < 12:
        raise HTTPException(422, "Password must contain at least 12 characters")

    user = db.scalar(select(AppUser).where(AppUser.email == email, AppUser.is_active.is_(True)))
    if not user:
        raise HTTPException(400, "Invalid or expired reset code")

    now = datetime.now(timezone.utc)
    reset = db.scalar(select(PasswordResetCode).where(
        PasswordResetCode.user_id == user.id,
        PasswordResetCode.used_at.is_(None),
        PasswordResetCode.expires_at > now,
    ).order_by(PasswordResetCode.created_at.desc()))
    if not reset:
        raise HTTPException(400, "Invalid or expired reset code")
    if reset.attempts >= 5:
        raise HTTPException(429, "Too many invalid attempts. Request a new code.")
    if not hmac.compare_digest(reset.code_hash, _hash_key(code)):
        reset.attempts += 1
        db.commit()
        raise HTTPException(400, "Invalid or expired reset code")

    record = db.scalar(select(UserPassword).where(UserPassword.user_id == user.id))
    if record:
        record.password_hash = _hash_password(password)
        record.failed_attempts = 0
        record.locked_until = None
    else:
        db.add(UserPassword(user_id=user.id, password_hash=_hash_password(password)))
    reset.used_at = now

    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    organization_id = memberships[0].organization_id if memberships else None
    sessions = db.scalars(select(ApiCredential).where(
        ApiCredential.user_id == user.id,
        ApiCredential.name == "Human login session",
        ApiCredential.revoked_at.is_(None),
    )).all()
    for session in sessions:
        session.revoked_at = now
    if organization_id:
        db.add(CrmActivity(
            organization_id=organization_id,
            user_id=user.id,
            activity_type="human_password_reset",
            summary="User reset password using an emailed one-time code",
            metadata_json={"email": user.email},
        ))
    db.commit()
    return {"reset": True, "message": "Password updated. You can sign in now."}


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
    now = datetime.now(timezone.utc)
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
        credential.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"logged_out": True}

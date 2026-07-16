import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth_models import ApiCredential, AppUser, CrmActivity, Membership, Organization
from .database import get_db

router = APIRouter(prefix="/auth", tags=["authentication"])

ROLE_RANK = {
    "viewer": 10,
    "va": 20,
    "acquisitions": 30,
    "disposition": 30,
    "transaction_coordinator": 30,
    "manager": 70,
    "admin": 90,
    "owner": 100,
}


@dataclass(frozen=True)
class Principal:
    organization_id: int
    organization_name: str
    user_id: int
    email: str
    name: str
    role: str


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"workspace-{secrets.token_hex(3)}"


def _new_key() -> str:
    return f"sahjony_live_{secrets.token_urlsafe(32)}"


def _valid_bootstrap_secret(provided: str | None) -> bool:
    configured = os.getenv("BOOTSTRAP_SECRET")
    if not configured or not provided:
        return False
    return secrets.compare_digest(provided, configured)


def _extract_token(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def get_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    token = _extract_token(authorization, x_api_key)
    if not token:
        raise HTTPException(401, "Missing API key")
    credential = db.scalar(select(ApiCredential).where(
        ApiCredential.key_hash == _hash_key(token), ApiCredential.revoked_at.is_(None)
    ))
    if not credential:
        raise HTTPException(401, "Invalid or revoked API key")
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == credential.organization_id,
        Membership.user_id == credential.user_id,
    ))
    user = db.get(AppUser, credential.user_id)
    organization = db.get(Organization, credential.organization_id)
    if not membership or not user or not organization or not user.is_active or not organization.is_active:
        raise HTTPException(403, "Workspace access disabled")
    credential.last_used_at = datetime.utcnow()
    db.commit()
    return Principal(
        organization_id=organization.id,
        organization_name=organization.name,
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
    )


def require_role(*roles: str):
    minimum = max((ROLE_RANK.get(role, 0) for role in roles), default=0)

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if ROLE_RANK.get(principal.role, 0) < minimum:
            raise HTTPException(403, "Insufficient role")
        return principal

    return dependency


@router.post("/bootstrap")
def bootstrap(payload: dict, x_bootstrap_secret: str | None = Header(default=None), db: Session = Depends(get_db)):
    existing = db.scalar(select(func.count(Organization.id))) or 0
    if existing > 0 and not _valid_bootstrap_secret(x_bootstrap_secret):
        raise HTTPException(403, "Bootstrap is locked")

    organization_name = str(payload.get("organization_name") or "SAHJONY Wholesale Operations").strip()
    owner_email = str(payload.get("owner_email") or "").strip().lower()
    owner_name = str(payload.get("owner_name") or "Owner").strip()
    if not owner_email or "@" not in owner_email:
        raise HTTPException(422, "Valid owner_email is required")

    base_slug = _slugify(organization_name)
    slug = base_slug
    counter = 2
    while db.scalar(select(Organization).where(Organization.slug == slug)):
        slug = f"{base_slug}-{counter}"
        counter += 1

    organization = Organization(name=organization_name, slug=slug)
    user = db.scalar(select(AppUser).where(AppUser.email == owner_email)) or AppUser(email=owner_email, name=owner_name)
    db.add_all([organization, user])
    db.flush()
    membership = Membership(organization_id=organization.id, user_id=user.id, role="owner")
    raw_key = _new_key()
    credential = ApiCredential(
        organization_id=organization.id,
        user_id=user.id,
        name="Owner primary key",
        key_prefix=raw_key[:18],
        key_hash=_hash_key(raw_key),
    )
    db.add_all([membership, credential])
    db.commit()
    return {
        "organization": {"id": organization.id, "name": organization.name, "slug": organization.slug},
        "owner": {"id": user.id, "email": user.email, "name": user.name, "role": "owner"},
        "api_key": raw_key,
        "warning": "Store this key securely. It is shown only once.",
    }


@router.post("/recover-owner-key")
def recover_owner_key(
    payload: dict,
    x_bootstrap_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not _valid_bootstrap_secret(x_bootstrap_secret):
        raise HTTPException(403, "Invalid recovery secret")

    owner_email = str(payload.get("owner_email") or "").strip().lower()
    organization_slug = str(payload.get("organization_slug") or "").strip().lower()
    if not owner_email or "@" not in owner_email:
        raise HTTPException(422, "Valid owner_email is required")

    query = (
        select(Membership)
        .join(AppUser, AppUser.id == Membership.user_id)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(
            Membership.role == "owner",
            AppUser.email == owner_email,
            AppUser.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )
    if organization_slug:
        query = query.where(Organization.slug == organization_slug)

    memberships = db.scalars(query).all()
    if len(memberships) != 1:
        raise HTTPException(404, "Unique active owner workspace not found")

    membership = memberships[0]
    user = db.get(AppUser, membership.user_id)
    organization = db.get(Organization, membership.organization_id)
    if not user or not organization:
        raise HTTPException(404, "Owner workspace not found")

    now = datetime.utcnow()
    active_credentials = db.scalars(select(ApiCredential).where(
        ApiCredential.organization_id == organization.id,
        ApiCredential.user_id == user.id,
        ApiCredential.revoked_at.is_(None),
    )).all()
    for credential in active_credentials:
        credential.revoked_at = now

    raw_key = _new_key()
    replacement = ApiCredential(
        organization_id=organization.id,
        user_id=user.id,
        name="Owner recovery key",
        key_prefix=raw_key[:18],
        key_hash=_hash_key(raw_key),
    )
    audit = CrmActivity(
        organization_id=organization.id,
        user_id=user.id,
        activity_type="owner_key_recovered",
        summary="Owner API key was securely recovered and previous owner keys were revoked",
        metadata_json={"revoked_key_count": len(active_credentials), "new_key_prefix": replacement.key_prefix},
    )
    db.add_all([replacement, audit])
    db.commit()
    db.refresh(replacement)

    return {
        "organization": {"id": organization.id, "name": organization.name, "slug": organization.slug},
        "owner": {"id": user.id, "email": user.email, "name": user.name, "role": "owner"},
        "api_key": raw_key,
        "revoked_key_count": len(active_credentials),
        "warning": "Store this key securely. It is shown only once.",
    }


@router.get("/me")
def me(principal: Principal = Depends(get_principal)):
    return principal.__dict__


@router.get("/team")
def list_team(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Membership, AppUser)
        .join(AppUser, AppUser.id == Membership.user_id)
        .where(Membership.organization_id == principal.organization_id)
        .order_by(AppUser.name)
    ).all()
    return [{
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "role": membership.role,
        "active": user.is_active,
    } for membership, user in rows]


@router.post("/team")
def add_team_member(
    payload: dict,
    principal: Principal = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    email = str(payload.get("email") or "").strip().lower()
    name = str(payload.get("name") or email.split("@")[0]).strip()
    role = str(payload.get("role") or "viewer").strip()
    if "@" not in email or role not in ROLE_RANK:
        raise HTTPException(422, "Valid email and role are required")
    user = db.scalar(select(AppUser).where(AppUser.email == email)) or AppUser(email=email, name=name)
    db.add(user)
    db.flush()
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == principal.organization_id,
        Membership.user_id == user.id,
    ))
    if membership:
        membership.role = role
    else:
        membership = Membership(organization_id=principal.organization_id, user_id=user.id, role=role)
        db.add(membership)
    db.commit()
    return {"user_id": user.id, "email": user.email, "name": user.name, "role": membership.role}


@router.post("/api-keys")
def create_api_key(
    payload: dict,
    principal: Principal = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    requested_user_id = int(payload.get("user_id") or principal.user_id)
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == principal.organization_id,
        Membership.user_id == requested_user_id,
    ))
    if not membership:
        raise HTTPException(404, "User is not in this organization")
    raw_key = _new_key()
    credential = ApiCredential(
        organization_id=principal.organization_id,
        user_id=requested_user_id,
        name=str(payload.get("name") or "API key"),
        key_prefix=raw_key[:18],
        key_hash=_hash_key(raw_key),
    )
    db.add(credential)
    db.commit()
    return {"id": credential.id, "api_key": raw_key, "prefix": credential.key_prefix,
            "warning": "Store this key securely. It is shown only once."}


@router.delete("/api-keys/{credential_id}")
def revoke_api_key(
    credential_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    credential = db.get(ApiCredential, credential_id)
    if not credential or credential.organization_id != principal.organization_id:
        raise HTTPException(404, "API key not found")
    credential.revoked_at = datetime.utcnow()
    db.commit()
    return {"id": credential.id, "revoked": True}

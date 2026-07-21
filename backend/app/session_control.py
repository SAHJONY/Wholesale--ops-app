from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import HUMAN_SESSION_IDLE_TIMEOUT, HUMAN_SESSION_MAX_AGE, Principal, _extract_token, _hash_key, get_principal
from .auth_models import ApiCredential, CrmActivity
from .database import get_db

router = APIRouter(prefix="/sessions", tags=["session security"])


def _current_credential(db: Session, authorization: str | None, x_api_key: str | None) -> ApiCredential | None:
    token = _extract_token(authorization, x_api_key)
    if not token:
        return None
    return db.scalar(select(ApiCredential).where(ApiCredential.key_hash == _hash_key(token)))


@router.get("/snapshot")
def snapshot(
    principal: Principal = Depends(get_principal),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    current = _current_credential(db, authorization, x_api_key)
    rows = db.scalars(select(ApiCredential).where(
        ApiCredential.organization_id == principal.organization_id,
        ApiCredential.user_id == principal.user_id,
        ApiCredential.name == "Human login session",
    ).order_by(ApiCredential.created_at.desc())).all()
    now = datetime.now(timezone.utc)
    sessions = []
    for item in rows:
        last_seen = item.last_used_at or item.created_at
        sessions.append({
            "id": item.id,
            "current": bool(current and current.id == item.id),
            "status": "revoked" if item.revoked_at else "active",
            "created_at": item.created_at,
            "last_used_at": item.last_used_at,
            "absolute_expires_at": item.created_at + HUMAN_SESSION_MAX_AGE,
            "idle_expires_at": last_seen + HUMAN_SESSION_IDLE_TIMEOUT,
            "expired": bool(item.revoked_at or now > item.created_at + HUMAN_SESSION_MAX_AGE or now > last_seen + HUMAN_SESSION_IDLE_TIMEOUT),
            "prefix": item.key_prefix,
        })
    return {
        "policy": {
            "absolute_hours": int(HUMAN_SESSION_MAX_AGE.total_seconds() // 3600),
            "idle_hours": int(HUMAN_SESSION_IDLE_TIMEOUT.total_seconds() // 3600),
            "single_active_session_on_login": True,
        },
        "summary": {
            "total": len(sessions),
            "active": sum(1 for item in sessions if item["status"] == "active" and not item["expired"]),
            "revoked_or_expired": sum(1 for item in sessions if item["status"] != "active" or item["expired"]),
        },
        "sessions": sessions,
    }


@router.post("/revoke-others")
def revoke_others(
    principal: Principal = Depends(get_principal),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    current = _current_credential(db, authorization, x_api_key)
    if not current or current.name != "Human login session":
        raise HTTPException(422, "Current credential is not a human login session")
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(ApiCredential).where(
        ApiCredential.organization_id == principal.organization_id,
        ApiCredential.user_id == principal.user_id,
        ApiCredential.name == "Human login session",
        ApiCredential.revoked_at.is_(None),
        ApiCredential.id != current.id,
    )).all()
    for item in rows:
        item.revoked_at = now
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="other_sessions_revoked",
        summary="User revoked all other active human sessions",
        metadata_json={"revoked_count": len(rows)},
    ))
    db.commit()
    return {"revoked": len(rows), "current_session_preserved": True}


@router.post("/{session_id}/revoke")
def revoke_session(
    session_id: int,
    principal: Principal = Depends(get_principal),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    current = _current_credential(db, authorization, x_api_key)
    item = db.get(ApiCredential, session_id)
    if not item or item.organization_id != principal.organization_id or item.user_id != principal.user_id or item.name != "Human login session":
        raise HTTPException(404, "Session not found")
    if current and current.id == item.id:
        raise HTTPException(422, "Use logout to end the current session")
    if not item.revoked_at:
        item.revoked_at = datetime.now(timezone.utc)
        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            activity_type="session_revoked",
            summary="User revoked a human login session",
            metadata_json={"session_id": item.id, "prefix": item.key_prefix},
        ))
        db.commit()
    return {"id": item.id, "revoked": True}

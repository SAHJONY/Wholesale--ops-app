from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agentic_voice_brain import SAFE_TOOL_NAMES, execute_tool
from .auth import Principal
from .auth_models import AppUser, Membership, Organization
from .database import get_db

router = APIRouter(prefix="/agentic-voice/internal", tags=["internal voice service"])
MAX_SKEW_SECONDS = 300
DOMAIN = b"sahjony-agentic-voice-service-v1"


def _root_secret() -> str:
    secret = str(os.getenv("OPENAI_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise HTTPException(503, "OPENAI_WEBHOOK_SECRET is not configured")
    return secret


def _service_key() -> bytes:
    return hmac.new(_root_secret().encode("utf-8"), DOMAIN, hashlib.sha256).digest()


def service_signature(timestamp: str, body: bytes) -> str:
    return hmac.new(_service_key(), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()


def verify_service_signature(timestamp: str | None, signature: str | None, body: bytes, now: int | None = None) -> None:
    if not timestamp or not signature:
        raise HTTPException(401, "Missing internal voice signature")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "Invalid internal voice timestamp") from exc
    current = int(time.time()) if now is None else int(now)
    if abs(current - ts) > MAX_SKEW_SECONDS:
        raise HTTPException(401, "Expired internal voice signature")
    expected = service_signature(timestamp, body)
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise HTTPException(401, "Invalid internal voice signature")


def _service_principal(db: Session, organization_id: int) -> Principal:
    organization = db.get(Organization, organization_id)
    if not organization or not organization.is_active:
        raise HTTPException(404, "Voice workspace not found")
    memberships = db.scalars(select(Membership).where(
        Membership.organization_id == organization_id,
        Membership.role.in_(["owner", "admin", "manager", "acquisitions"]),
    ).order_by(Membership.id)).all()
    rank = {"owner": 4, "admin": 3, "manager": 2, "acquisitions": 1}
    memberships = sorted(memberships, key=lambda item: (-rank.get(item.role, 0), item.id))
    for membership in memberships:
        user = db.get(AppUser, membership.user_id)
        if user and user.is_active:
            return Principal(
                organization_id=organization.id,
                organization_name=organization.name,
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=membership.role,
            )
    raise HTTPException(403, "No active acquisitions-capable user in this workspace")


@router.post("/tool")
async def internal_tool(
    request: Request,
    x_sahjony_voice_timestamp: str | None = Header(default=None),
    x_sahjony_voice_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    verify_service_signature(x_sahjony_voice_timestamp, x_sahjony_voice_signature, body)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Invalid internal voice JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "Internal voice payload must be an object")
    tool_name = str(payload.get("tool_name") or "").strip()
    if tool_name not in SAFE_TOOL_NAMES:
        raise HTTPException(403, "Voice tool is not authorized")
    try:
        organization_id = int(payload.get("organization_id") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "organization_id is required") from exc
    if organization_id <= 0:
        raise HTTPException(422, "organization_id is required")
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise HTTPException(422, "arguments must be an object")
    principal = _service_principal(db, organization_id)
    result = execute_tool(tool_name, arguments, principal, db)
    return {
        "organization_id": organization_id,
        "tool_name": tool_name,
        "result": result,
        "service_authenticated": True,
    }

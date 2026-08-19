from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import CrmActivity
from .database import get_db
from .voice_models import VoiceCall

router = APIRouter(prefix="/internal/bland-test", tags=["Bland one-time test"])
AUTH_ACTIVITY = "bland_test_authorization"


def _api_key() -> str:
    """Return the Bland credential without common copy/paste wrappers.

    Vercel stores environment-variable values literally. A key pasted as
    '"key"' or 'Bearer key' therefore reaches Bland with those characters and
    is rejected with 401 even though the secret is present. We normalize only
    transport wrappers; the underlying credential is never logged or returned.
    """
    value = str(os.getenv("BLAND_AI_API_KEY") or os.getenv("BLAND_API_KEY") or "").strip()
    if not value:
        raise HTTPException(503, "Bland API key is not configured")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value:
        raise HTTPException(503, "Bland API key is empty after normalization")
    return value


def _nonce_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@router.get("/run-once")
async def run_once(nonce: str = Query(min_length=20, max_length=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == 1,
        CrmActivity.activity_type == AUTH_ACTIVITY,
    ).order_by(CrmActivity.id.desc()).limit(20)).all()
    expected = _nonce_hash(nonce)
    authorization = None
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if meta.get("status") == "pending" and secrets.compare_digest(str(meta.get("nonce_hash") or ""), expected):
            authorization = row
            break
    if not authorization:
        raise HTTPException(404, "One-time Bland test authorization not found or already consumed")

    meta = dict(authorization.metadata_json or {})
    phone = str(meta.get("phone") or "").strip()
    if not phone.startswith("+"):
        raise HTTPException(422, "Authorized test phone is invalid")

    body = {
        "phone_number": phone,
        "task": (
            "This is an owner-authorized SAHJONY Bland AI voice integration test. "
            "Confirm that the Bland AI phone system is working, say the call is not recorded, "
            "thank Juan, and end the call. Do not discuss sales, real estate, offers, or any other topic."
        ),
        "first_sentence": (
            "Hi Juan, this is the automated SAHJONY Bland AI phone system test. "
            "Your voice integration is working, and this call is not recorded."
        ),
        "record": False,
        "wait_for_greeting": True,
        "max_duration": 2,
        "metadata": {
            "organization_id": 1,
            "authorization_activity_id": authorization.id,
            "source": "owner_authorized_bland_test",
            "purpose": "voice_integration_validation",
        },
    }
    from_number = str(os.getenv("BLAND_DEFAULT_FROM_NUMBER") or os.getenv("BLAND_DEFAULT_CALLER_ID") or "").strip()
    if from_number:
        body["from"] = from_number

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": _api_key(), "Content-Type": "application/json"},
            json=body,
        )
    try:
        result = response.json()
    except ValueError:
        result = {"message": response.text[:500]}
    if response.status_code >= 400 or str(result.get("status") or "").lower() == "error":
        error_code = None
        errors = result.get("errors") if isinstance(result, dict) else None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            error_code = errors[0].get("error")
        detail = result.get("message") if isinstance(result, dict) else None
        raise HTTPException(502, f"Bland test call rejected: {error_code or detail or response.status_code}")

    call_id = str(result.get("call_id") or "").strip() or None
    meta["status"] = "consumed"
    meta["consumed_at"] = datetime.now(timezone.utc).isoformat()
    meta["provider_call_id"] = call_id
    authorization.metadata_json = meta
    authorization.summary = "Owner-authorized one-time Bland voice test consumed"

    db.add(VoiceCall(
        organization_id=1,
        lead_id=None,
        direction="outbound",
        contact=phone,
        state=str(meta.get("state") or "TX"),
        provider="bland",
        provider_call_id=call_id,
        decision_id=None,
        status=str(result.get("status") or "queued"),
        outcome="owner_authorized_system_test",
        ai_disclosed=True,
        recorded=False,
        recording_consent_basis=None,
        verbal_opt_out=False,
        evidence={"owner_authorized": True, "purpose": "voice_integration_validation", "recorded": False},
    ))
    db.add(CrmActivity(
        organization_id=1,
        user_id=1,
        lead_id=None,
        activity_type="bland_test_call_dispatched",
        summary="One-time owner-authorized Bland AI test call dispatched",
        metadata_json={"call_id": call_id, "recorded": False, "sms_sent": 0},
    ))
    db.commit()
    return {
        "status": str(result.get("status") or "queued"),
        "call_id": call_id,
        "provider": "bland",
        "recorded": False,
        "sms_sent": 0,
    }

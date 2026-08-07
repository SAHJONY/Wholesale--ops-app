"""Bland Messaging adapter for SAHJONY seller SMS.

Bland is the communications provider for both SMS and voice. This module accepts
Bland message/status webhooks, verifies Bland's HMAC signature over the raw body,
and routes seller-authored SMS messages into the agentic acquisition engine.

The webhook never grants outbound authority. Agent replies remain drafts until
they pass the existing SMS preflight, compliance decision, owner approval, and
controlled outbound gateway.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .auth_models import CrmActivity
from .compliance import normalize_phone
from .database import get_db
from .outbound_models import OutboundRequest
from .sms_agentic import process_message
from .sms_engine import classify_inbound, suppress
from .sms_models import SmsMessage

router = APIRouter(prefix="/webhooks/bland", tags=["bland messaging"])


def _webhook_secret() -> str:
    return str(os.getenv("BLAND_WEBHOOK_SIGNING_SECRET") or os.getenv("BLAND_WEBHOOK_SECRET") or "").strip()


def verify_bland_signature(raw_body: bytes, signature: str | None) -> None:
    secret = _webhook_secret()
    if not secret:
        raise HTTPException(503, "Bland webhook signing secret is not configured")
    if not signature:
        raise HTTPException(401, "Missing Bland webhook signature")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip()):
        raise HTTPException(401, "Invalid Bland webhook signature")


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("metadata")
    return value if isinstance(value, dict) else {}


def _principal_from_metadata(metadata: dict[str, Any]) -> Principal | None:
    try:
        organization_id = int(metadata.get("organization_id") or 0)
        user_id = int(metadata.get("requested_by_user_id") or 0)
    except (TypeError, ValueError):
        return None
    if organization_id <= 0 or user_id <= 0:
        return None
    return Principal(
        organization_id=organization_id,
        organization_name="SAHJONY Wholesale OS",
        user_id=user_id,
        email="bland-webhook@internal",
        name="Bland Messaging Webhook",
        role="owner",
    )


def _lead_id(metadata: dict[str, Any]) -> int | None:
    try:
        value = int(metadata.get("lead_id") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _message_text(payload: dict[str, Any]) -> str:
    value = payload.get("message")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("content", "text", "body", "message"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _event_key(payload: dict[str, Any], text: str) -> str:
    canonical = "|".join([
        str(payload.get("conversation_id") or ""),
        str(payload.get("sender") or ""),
        str(payload.get("created_at") or ""),
        text,
    ])
    return "bland:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _update_conversation_status(db: Session, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not conversation_id:
        return
    request = db.scalar(select(OutboundRequest).where(
        OutboundRequest.provider == "bland",
        OutboundRequest.provider_reference == conversation_id,
    ).order_by(OutboundRequest.created_at.desc()))
    if request:
        status = str(payload.get("status") or "").strip().lower()
        if status:
            request.provider_status = status
            if status in {"ended", "inactive", "blacklisted"}:
                request.status = "completed" if status == "ended" else status

    organization_id = metadata.get("organization_id")
    user_id = metadata.get("requested_by_user_id")
    lead_id = metadata.get("lead_id")
    if organization_id and user_id:
        db.add(CrmActivity(
            organization_id=int(organization_id),
            user_id=int(user_id),
            lead_id=int(lead_id) if lead_id else None,
            activity_type="bland_sms_status",
            summary=f"Bland SMS conversation {conversation_id} status: {payload.get('status') or 'event'}",
            metadata_json={
                "conversation_id": conversation_id,
                "status": payload.get("status"),
                "channel": payload.get("channel"),
                "message_count": payload.get("message_count"),
                "summary": payload.get("summary"),
                "dispositions": payload.get("dispositions"),
            },
        ))


@router.post("/messaging")
async def bland_messaging_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    verify_bland_signature(raw_body, request.headers.get("x-webhook-signature"))
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Invalid Bland webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "Invalid Bland webhook payload")

    channel = str(payload.get("channel") or "").strip().lower()
    if channel and channel != "sms":
        return {"accepted": True, "routed": False, "reason": "non_sms_channel"}

    metadata = _metadata(payload)
    principal = _principal_from_metadata(metadata)
    lead_id = _lead_id(metadata)

    # Status webhooks do not contain a new seller turn. Keep provider state and
    # analytics in sync, then acknowledge without invoking the conversation AI.
    sender = str(payload.get("sender") or "").strip().upper()
    text = _message_text(payload)
    if sender != "USER" or not text:
        _update_conversation_status(db, payload, metadata)
        db.commit()
        return {
            "accepted": True,
            "routed": False,
            "conversation_id": payload.get("conversation_id"),
            "event": "status_or_agent_message",
        }

    # SAHJONY-created Bland conversations always carry these metadata values.
    # If they are missing we fail closed: accept the provider webhook so it is
    # not retried forever, but do not attach a seller message to the wrong desk.
    if not principal or not lead_id:
        return {
            "accepted": True,
            "routed": False,
            "reason": "missing_sahjony_conversation_metadata",
            "conversation_id": payload.get("conversation_id"),
        }

    contact = normalize_phone(str(payload.get("phone_number") or ""))
    if not contact:
        raise HTTPException(422, "Bland SMS webhook is missing phone_number")

    event_key = _event_key(payload, text)
    existing = db.scalar(select(SmsMessage).where(
        SmsMessage.organization_id == principal.organization_id,
        SmsMessage.provider_message_id == event_key,
    ))
    if existing:
        return {
            "accepted": True,
            "routed": False,
            "duplicate": True,
            "message_id": existing.id,
        }

    kind, keyword = classify_inbound(text)
    message = SmsMessage(
        organization_id=principal.organization_id,
        lead_id=lead_id,
        direction="inbound",
        contact=contact,
        body=text,
        provider_message_id=event_key,
        keyword=keyword or None,
        triggered_opt_out=kind == "opt_out",
        status="received",
        evidence={
            "provider": "bland",
            "conversation_id": payload.get("conversation_id"),
            "agent_number": payload.get("agent_number"),
            "created_at": payload.get("created_at"),
            "pathway_id": payload.get("pathway_id"),
            "pathway_version": payload.get("pathway_version"),
            "pathway_tags": payload.get("pathway_tags"),
            "classified_as": kind,
        },
    )
    db.add(message)
    db.flush()

    if kind == "opt_out":
        suppress(
            db,
            principal.organization_id,
            contact,
            "recipient_opt_out",
            f"bland_sms:{keyword}",
            lead_id,
        )
    db.commit()
    db.refresh(message)

    result = process_message(db, principal, message)
    return {
        "accepted": True,
        "routed": True,
        "conversation_id": payload.get("conversation_id"),
        **result,
    }


@router.get("/messaging/health")
def bland_messaging_health():
    return {
        "status": "ok",
        "provider": "bland",
        "sms_endpoint": "https://api.bland.ai/v1/sms/send",
        "api_key_configured": bool(os.getenv("BLAND_AI_API_KEY")),
        "sms_number_configured": bool(bland_number := (
            os.getenv("BLAND_SMS_AGENT_NUMBER")
            or os.getenv("BLAND_MESSAGING_NUMBER")
            or os.getenv("BLAND_DEFAULT_FROM_NUMBER")
            or os.getenv("BLAND_DEFAULT_CALLER_ID")
        )),
        "webhook_signing_configured": bool(_webhook_secret()),
        "sms_number_last4": str(bland_number)[-4:] if bland_number else None,
        "transport": "bland_only",
    }

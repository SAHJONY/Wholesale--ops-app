from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .compliance_models import ComplianceDecision, ContactSuppression
from .database import get_db
from .models import Lead
from .outbound_models import OutboundRequest
from .voice_models import VoiceCall

router = APIRouter(prefix="/bland-phone", tags=["Bland AI phone system"])

CALL_DECISION_TTL = timedelta(minutes=15)
AUTOPILOT_CALL_GAP = timedelta(hours=24)
SUPPORTED_CHANNEL = "automated_call"
PROVIDER = "bland"


def _enabled(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _api_key() -> str:
    value = str(os.getenv("BLAND_AI_API_KEY") or "").strip()
    if not value:
        raise HTTPException(503, "BLAND_AI_API_KEY is not configured")
    return value


def _business_number() -> str | None:
    return str(
        os.getenv("BLAND_BUSINESS_PHONE_NUMBER")
        or os.getenv("BLAND_DEFAULT_FROM_NUMBER")
        or os.getenv("BLAND_DEFAULT_CALLER_ID")
        or ""
    ).strip() or None


def _webhook_url() -> str | None:
    return str(os.getenv("BLAND_PHONE_WEBHOOK_URL") or "").strip() or None


def _default_org_id() -> int:
    raw = str(os.getenv("BLAND_DEFAULT_ORGANIZATION_ID") or "1").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 1


def _workspace_has_lead(db: Session, organization_id: int, lead_id: int) -> bool:
    return db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    )) is not None


def _find_lead_by_phone(db: Session, organization_id: int, phone: str) -> Lead | None:
    linked_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    if not linked_ids:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if not digits:
        return None
    candidates = db.scalars(select(Lead).where(Lead.id.in_(linked_ids), Lead.status != "deleted")).all()
    matches = [lead for lead in candidates if "".join(ch for ch in str(lead.phone or "") if ch.isdigit())[-10:] == digits]
    return matches[0] if len(matches) == 1 else None


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    secret = str(os.getenv("BLAND_WEBHOOK_SECRET") or "").strip()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _safe_task(lead: Lead) -> str:
    name = str(lead.seller_name or "there").strip()
    return (
        f"You are the automated acquisitions assistant for SAHJONY. Speak naturally and professionally with {name}. "
        "At the start, identify SAHJONY and disclose that you are an automated assistant. "
        "Your purpose is to understand whether the person wants to discuss selling the property and, if they do, capture only explicit Motivation, Timeline, Condition, and Price. "
        "Never invent ownership, liens, ARV, repairs, title status, legal outcomes, or contract terms. "
        "Never make a binding offer or promise a price. Never pressure the person. "
        "If they ask not to be called, acknowledge it, end the sales conversation, and mark opt-out in the call outcome. "
        "If they request a human, have legal/title complexity, or want to negotiate binding terms, escalate to the configured human acquisitions number."
    )


def _fresh_allowed_decision(db: Session, organization_id: int, lead_id: int, contact: str) -> ComplianceDecision | None:
    threshold = datetime.now(timezone.utc) - CALL_DECISION_TTL
    return db.scalar(select(ComplianceDecision).where(
        ComplianceDecision.organization_id == organization_id,
        ComplianceDecision.lead_id == lead_id,
        ComplianceDecision.channel == SUPPORTED_CHANNEL,
        ComplianceDecision.contact == contact,
        ComplianceDecision.allowed.is_(True),
        ComplianceDecision.created_at >= threshold,
    ).order_by(ComplianceDecision.created_at.desc()))


def _suppressed(db: Session, organization_id: int, contact: str) -> bool:
    return db.scalar(select(ContactSuppression.id).where(
        ContactSuppression.organization_id == organization_id,
        ContactSuppression.contact == contact,
        ContactSuppression.channel.in_([SUPPORTED_CHANNEL, "phone", "all"]),
        ContactSuppression.active.is_(True),
    )) is not None


def _called_recently(db: Session, organization_id: int, contact: str) -> bool:
    threshold = datetime.now(timezone.utc) - AUTOPILOT_CALL_GAP
    return db.scalar(select(VoiceCall.id).where(
        VoiceCall.organization_id == organization_id,
        VoiceCall.direction == "outbound",
        VoiceCall.contact == contact,
        VoiceCall.created_at >= threshold,
    )) is not None


async def _send_call(lead: Lead, organization_id: int, contact: str, decision: ComplianceDecision) -> dict[str, Any]:
    body: dict[str, Any] = {
        "phone_number": contact,
        "task": _safe_task(lead),
        "first_sentence": "Hi, this is the automated acquisitions assistant with SAHJONY. Is now an okay time for a brief conversation?",
        "record": False,
        "wait_for_greeting": True,
        "max_duration": 10,
        "metadata": {
            "organization_id": organization_id,
            "lead_id": lead.id,
            "compliance_decision_id": decision.id,
            "source": "sahjony_bland_phone_autopilot",
        },
        "summary_prompt": "Summarize seller intent, Motivation, Timeline, Condition, Price, human-transfer request, and any opt-out. Do not infer missing facts.",
    }
    business_number = _business_number()
    if business_number:
        body["from"] = business_number
    webhook = _webhook_url()
    if webhook:
        body["webhook"] = webhook
        body["webhook_events"] = [{"type": "call"}]
    transfer = str(os.getenv("VOICE_HUMAN_TRANSFER_TARGET") or "").strip()
    if transfer:
        body["transfer_phone_number"] = transfer

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": _api_key(), "Content-Type": "application/json"},
            json=body,
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:1000]}
    if response.status_code >= 400 or str(payload.get("status") or "").lower() == "error":
        raise HTTPException(502, f"Bland rejected the call: {payload.get('message') or response.status_code}")
    return payload


@router.get("/readiness")
def readiness(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    configured = {
        "api_key": bool(os.getenv("BLAND_AI_API_KEY")),
        "business_phone_number": bool(_business_number()),
        "webhook_url": bool(_webhook_url()),
        "webhook_signing_secret": bool(os.getenv("BLAND_WEBHOOK_SECRET")),
        "inbound_enabled": _enabled("BLAND_INBOUND_ENABLED", True),
        "autonomous_outbound_enabled": _enabled("BLAND_AUTONOMOUS_OUTBOUND_ENABLED", False),
        "sms_enabled": False,
        "call_recording": False,
    }
    inbound_count = int(db.scalar(select(func.count()).select_from(VoiceCall).where(
        VoiceCall.organization_id == principal.organization_id, VoiceCall.direction == "inbound")) or 0)
    outbound_count = int(db.scalar(select(func.count()).select_from(VoiceCall).where(
        VoiceCall.organization_id == principal.organization_id, VoiceCall.direction == "outbound")) or 0)
    return {
        "provider": PROVIDER,
        "mode": "voice_only",
        "configured": configured,
        "inbound_ready": all((configured["api_key"], configured["business_phone_number"], configured["webhook_url"], configured["webhook_signing_secret"], configured["inbound_enabled"])),
        "outbound_ready": all((configured["api_key"], configured["business_phone_number"], configured["autonomous_outbound_enabled"])),
        "production_evidence": {"inbound_calls": inbound_count, "outbound_calls": outbound_count},
        "production_proven": inbound_count > 0 and outbound_count > 0,
        "policy": {
            "inbound": "24/7 autonomous reception",
            "outbound": "autonomous only after fresh allowed call-compliance decision and suppression check",
            "sms": "disabled until owner re-enables",
            "recording": "disabled",
        },
    }


@router.post("/autopilot/run")
async def run_autopilot(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    if not _enabled("BLAND_AUTONOMOUS_OUTBOUND_ENABLED", False):
        raise HTTPException(503, "Autonomous Bland outbound calling is not enabled in production")
    limit = max(1, min(int(payload.get("limit") or 5), 10))
    linked_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())
    leads = db.scalars(select(Lead).where(Lead.id.in_(linked_ids), Lead.status != "deleted")).all() if linked_ids else []
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for lead in leads:
        if len(queued) >= limit:
            break
        contact = str(lead.phone or "").strip()
        if not contact:
            continue
        decision = _fresh_allowed_decision(db, principal.organization_id, lead.id, contact)
        if not decision:
            skipped.append({"lead_id": lead.id, "reason": "no_fresh_allowed_call_compliance_decision"})
            continue
        if _suppressed(db, principal.organization_id, contact):
            skipped.append({"lead_id": lead.id, "reason": "suppressed"})
            continue
        if _called_recently(db, principal.organization_id, contact):
            skipped.append({"lead_id": lead.id, "reason": "24h_call_frequency_guard"})
            continue

        result = await _send_call(lead, principal.organization_id, contact, decision)
        call_id = str(result.get("call_id") or "") or None
        request = OutboundRequest(
            organization_id=principal.organization_id,
            lead_id=lead.id,
            compliance_decision_id=decision.id,
            channel=SUPPORTED_CHANNEL,
            provider=PROVIDER,
            contact=contact,
            status="queued",
            content={"task": _safe_task(lead), "record": False, "source": "bland_phone_autopilot"},
            requested_by_user_id=principal.user_id,
            provider_reference=call_id,
            provider_status=str(result.get("status") or "queued"),
            provider_response={k: result.get(k) for k in ("status", "message", "call_id", "batch_id")},
            dispatched_by_user_id=principal.user_id,
            dispatched_at=datetime.now(timezone.utc),
        )
        db.add(request)
        db.add(VoiceCall(
            organization_id=principal.organization_id,
            lead_id=lead.id,
            direction="outbound",
            contact=contact,
            state=getattr(getattr(lead, "property", None), "state", None),
            provider=PROVIDER,
            provider_call_id=call_id,
            decision_id=decision.id,
            status="queued",
            ai_disclosed=True,
            recorded=False,
            recording_consent_basis=None,
            evidence={"autonomous": True, "provider": PROVIDER, "compliance_decision_id": decision.id},
        ))
        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            lead_id=lead.id,
            activity_type="bland_autonomous_outbound_queued",
            summary="Compliant autonomous Bland AI phone call queued",
            metadata_json={"call_id": call_id, "decision_id": decision.id, "recorded": False},
        ))
        db.commit()
        queued.append({"lead_id": lead.id, "call_id": call_id, "status": result.get("status")})

    return {"evaluated": len(leads), "queued": queued, "skipped": skipped[:50], "sms_sent": 0, "recording": False}


@router.post("/webhooks/call")
async def bland_call_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not _verify_signature(raw, request.headers.get("x-webhook-signature")):
        raise HTTPException(401, "Invalid Bland webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid Bland webhook payload") from exc

    organization_id = int((payload.get("metadata") or {}).get("organization_id") or _default_org_id())
    call_id = str(payload.get("call_id") or "").strip() or None
    direction = str(payload.get("direction") or "").lower()
    if direction not in {"inbound", "outbound"}:
        direction = "inbound" if str(payload.get("inbound") or "").lower() in {"true", "1"} else "outbound"
    phone = str(payload.get("phone_number") or payload.get("from") or payload.get("to") or "").strip()
    lead_id_raw = (payload.get("metadata") or {}).get("lead_id")
    lead = db.get(Lead, int(lead_id_raw)) if str(lead_id_raw or "").isdigit() else _find_lead_by_phone(db, organization_id, phone)
    if lead and not _workspace_has_lead(db, organization_id, lead.id):
        lead = None

    row = db.scalar(select(VoiceCall).where(VoiceCall.organization_id == organization_id, VoiceCall.provider_call_id == call_id)) if call_id else None
    status = str(payload.get("status") or payload.get("call_status") or "completed").lower()
    outcome = str(payload.get("disposition") or payload.get("outcome") or "").strip() or None
    opt_out = bool(payload.get("verbal_opt_out")) or str(outcome or "").lower() in {"do_not_call", "opt_out", "dnc"}

    if not row:
        row = VoiceCall(
            organization_id=organization_id,
            lead_id=lead.id if lead else None,
            direction=direction,
            contact=phone,
            state=getattr(getattr(lead, "property", None), "state", None) if lead else None,
            provider=PROVIDER,
            provider_call_id=call_id,
            decision_id=None,
            status=status,
            outcome=outcome,
            duration_seconds=float(payload.get("call_length") or payload.get("duration") or 0) or None,
            ai_disclosed=True,
            recorded=False,
            recording_consent_basis=None,
            verbal_opt_out=opt_out,
            transcript_excerpt=str(payload.get("concatenated_transcript") or payload.get("transcript") or "")[:2000] or None,
            evidence={"webhook_verified": True, "provider": PROVIDER, "summary": payload.get("summary")},
        )
        db.add(row)
    else:
        row.status = status
        row.outcome = outcome
        row.verbal_opt_out = row.verbal_opt_out or opt_out
        row.duration_seconds = float(payload.get("call_length") or payload.get("duration") or 0) or row.duration_seconds
        row.transcript_excerpt = str(payload.get("concatenated_transcript") or payload.get("transcript") or row.transcript_excerpt or "")[:2000] or None
        row.recorded = False
        row.evidence = {**(row.evidence or {}), "webhook_verified": True, "summary": payload.get("summary")}

    if opt_out and phone:
        existing = db.scalar(select(ContactSuppression).where(
            ContactSuppression.organization_id == organization_id,
            ContactSuppression.contact == phone,
            ContactSuppression.channel.in_(["phone", "all"]),
            ContactSuppression.active.is_(True),
        ))
        if not existing:
            db.add(ContactSuppression(
                organization_id=organization_id,
                contact=phone,
                channel="phone",
                reason="verbal_opt_out_bland_call",
                active=True,
            ))

    db.add(CrmActivity(
        organization_id=organization_id,
        user_id=None,
        lead_id=lead.id if lead else None,
        activity_type="bland_call_webhook_received",
        summary=f"Bland {direction} call {status}",
        metadata_json={"call_id": call_id, "outcome": outcome, "opt_out": opt_out, "webhook_verified": True},
    ))
    db.commit()
    return {"accepted": True, "call_id": call_id, "lead_id": lead.id if lead else None, "status": status, "opt_out": opt_out}

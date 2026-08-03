import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .compliance import normalize_contact
from .compliance_models import ComplianceDecision, ContactSuppression
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .models import Approval, Lead
from .outbound_models import OutboundRequest
from .sms_models import SmsMessage
from .voice_engine import discloses_ai, validate_call_script
from .voice_models import VoiceCall

router = APIRouter(prefix="/outbound", tags=["controlled outbound gateway"])

DECISION_TTL = timedelta(minutes=15)

VOICE_CHANNELS = frozenset({"automated_call", "live_call"})

# +, a non-zero country code, then 7 to 14 more digits.
E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def caller_id() -> str | None:
    """The number outbound calls are placed from, or None if unusable.

    Validated rather than passed through. A caller ID copied out of a chat
    window or a dashboard often arrives wrapped in typographic quotes, and
    Vercel stores an environment variable exactly as pasted -- so the value
    becomes "“+13465214387”" and every call fails at the provider with an
    error that says nothing about quotes.
    """
    for name in ("BLAND_DEFAULT_FROM_NUMBER", "BLAND_DEFAULT_CALLER_ID"):
        raw = str(os.getenv(name) or "").strip()
        if not raw:
            continue
        if E164.match(raw):
            return raw
        raise HTTPException(503, (
            f"{name} is not a valid E.164 number: {raw!r}. Expected +15551234567 "
            "with no quotes, spaces or dashes."
        ))
    return None


def _opening_line(request: OutboundRequest) -> str:
    """The words the person actually hears first.

    ``first_sentence`` is spoken verbatim when set. Otherwise Bland improvises
    the opening from ``task``, so the disclosure has to be instructed there.
    Both are joined rather than picking one, because a disclosure in either
    place is a real disclosure and refusing it would only teach people to
    duplicate the sentence.
    """
    content = request.content or {}
    return " ".join(
        str(content.get(field) or "") for field in ("first_sentence", "task")
    ).strip()


def _will_record(request: OutboundRequest) -> bool:
    """Whether this call would be recorded.

    ``_dispatch_bland`` hardcodes ``record: False`` and does not pass the field
    through, so today this is always False. It is read from content anyway so
    that the all-party consent check is already standing if recording is ever
    made configurable -- the gate should not have to be remembered later.
    """
    return bool((request.content or {}).get("record"))


def _call_state(db: Session, request: OutboundRequest) -> str | None:
    """The lead's state, which decides the recording rule.

    Returns None when unknown, and ``requires_all_party_consent`` reads None as
    all-party. That is the intended direction: a missing state is missing
    information, and only one of the two guesses is a criminal exposure.
    """
    lead = db.get(Lead, request.lead_id) if request.lead_id else None
    return (getattr(lead, "state", None) or None) if lead else None


def _validate_channel_provider(channel: str, provider: str) -> None:
    allowed = {("sms", "twilio"), ("automated_call", "bland")}
    if (channel, provider) not in allowed:
        raise HTTPException(422, "Supported combinations are sms/twilio and automated_call/bland")


def _decision_for_request(db: Session, principal: Principal, lead_id: int, decision_id: int,
                          channel: str, contact: str) -> ComplianceDecision:
    decision = db.get(ComplianceDecision, decision_id)
    if not decision:
        raise HTTPException(404, "Compliance decision not found")
    if decision.organization_id != principal.organization_id or decision.lead_id != lead_id:
        raise HTTPException(403, "Compliance decision is outside this workspace")
    if decision.channel != channel or decision.contact != contact:
        raise HTTPException(422, "Compliance decision does not match the exact channel and contact")
    if not decision.allowed:
        raise HTTPException(422, "Compliance decision is blocked")
    if datetime.now(timezone.utc) - decision.created_at > DECISION_TTL:
        raise HTTPException(422, "Compliance decision expired; evaluate again")
    return decision


def _active_suppression(db: Session, principal: Principal, channel: str, contact: str):
    channels = [channel, "all"]
    if channel in {"sms", "automated_call"}:
        channels.append("phone")
    return db.scalar(select(ContactSuppression).where(
        ContactSuppression.organization_id == principal.organization_id,
        ContactSuppression.contact == contact,
        ContactSuppression.channel.in_(channels),
        ContactSuppression.active.is_(True),
    ))


def _approved(db: Session, request_id: int) -> Approval | None:
    return db.scalar(select(Approval).where(
        Approval.entity_type == "outbound_request",
        Approval.entity_id == request_id,
        Approval.status == "approved",
    ).order_by(Approval.decided_at.desc()))


@router.post("/requests")
def create_outbound_request(
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    lead_id = int(payload.get("lead_id") or 0)
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")

    channel = str(payload.get("channel") or "").strip().lower()
    provider = str(payload.get("provider") or "").strip().lower()
    _validate_channel_provider(channel, provider)
    raw_contact = str(payload.get("contact") or (lead.phone if channel != "email" else lead.email) or "")
    contact = normalize_contact(channel, raw_contact)
    if not contact:
        raise HTTPException(422, "Contact is required")

    decision_id = int(payload.get("compliance_decision_id") or 0)
    _decision_for_request(db, principal, lead_id, decision_id, channel, contact)

    content = payload.get("content") or {}
    if channel == "sms" and not str(content.get("body") or "").strip():
        raise HTTPException(422, "SMS body is required")
    if channel == "automated_call" and not (
        str(content.get("task") or "").strip() or str(content.get("pathway_id") or "").strip()
    ):
        raise HTTPException(422, "Bland task or pathway_id is required")

    request = OutboundRequest(
        organization_id=principal.organization_id,
        lead_id=lead_id,
        compliance_decision_id=decision_id,
        channel=channel,
        provider=provider,
        contact=contact,
        status="pending_approval",
        content=content,
        requested_by_user_id=principal.user_id,
    )
    db.add(request)
    db.flush()
    _workspace_link(db, principal.organization_id, "outbound_request", request.id)

    approval = Approval(
        action_type=f"dispatch_{channel}",
        status="pending",
        entity_type="outbound_request",
        entity_id=request.id,
        summary=f"Approve {channel.replace('_', ' ')} to {lead.seller_name} via {provider}",
        payload={
            "outbound_request_id": request.id,
            "lead_id": lead_id,
            "provider": provider,
            "channel": channel,
            "contact": contact,
        },
    )
    db.add(approval)
    db.flush()
    _workspace_link(db, principal.organization_id, "approval", approval.id)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        activity_type="outbound_requested",
        summary=f"{channel} request created for {lead.seller_name}; owner approval required",
        metadata_json={"request_id": request.id, "approval_id": approval.id, "provider": provider},
    ))
    db.commit()
    return {
        "request_id": request.id,
        "status": request.status,
        "approval_id": approval.id,
        "approval_required": True,
        "dispatch_allowed": False,
    }


async def _dispatch_twilio(request: OutboundRequest) -> dict:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    # Twilio's own sender only. This used to fall back to
    # BLAND_DEFAULT_FROM_NUMBER, which meant that with no Twilio sender
    # configured, texts went out from the Bland voice number -- a number that
    # is not registered for A2P 10DLC messaging. Carriers either reject that
    # traffic or fine it, and neither failure points back here.
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    if not account_sid or not auth_token or not (from_number or messaging_service_sid):
        raise HTTPException(503, "Twilio credentials or sender are not configured")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    form = {"To": request.contact, "Body": str(request.content.get("body") or "")}
    if messaging_service_sid:
        form["MessagingServiceSid"] = messaging_service_sid
    else:
        form["From"] = from_number
    callback = os.getenv("TWILIO_STATUS_CALLBACK_URL")
    if callback:
        form["StatusCallback"] = callback

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, data=form, auth=(account_sid, auth_token))
    try:
        data = response.json()
    except ValueError:
        data = {"body": response.text[:1000]}
    if response.status_code >= 400:
        raise HTTPException(502, f"Twilio rejected the message: {data.get('message') or response.status_code}")
    return {
        "provider_reference": data.get("sid"),
        "provider_status": data.get("status") or "queued",
        "provider_response": {k: data.get(k) for k in ("sid", "status", "error_code", "error_message")},
    }


async def _dispatch_bland(request: OutboundRequest) -> dict:
    api_key = os.getenv("BLAND_AI_API_KEY")
    if not api_key:
        raise HTTPException(503, "BLAND_AI_API_KEY is not configured")
    body = {
        "phone_number": request.contact,
        "record": False,
        "metadata": {
            "outbound_request_id": request.id,
            "lead_id": request.lead_id,
            "organization_id": request.organization_id,
        },
    }
    for field in (
        "task", "pathway_id", "pathway_version", "voice", "language", "first_sentence",
        "wait_for_greeting", "max_duration", "from", "timezone", "transfer_phone_number",
        "summary_prompt", "webhook", "webhook_events", "request_data",
    ):
        value = request.content.get(field)
        if value not in (None, ""):
            body[field] = value
    if "from" not in body:
        default_from = caller_id()
        if default_from:
            body["from"] = default_from

    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": api_key, "Content-Type": "application/json"},
            json=body,
        )
    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text[:1000]}
    if response.status_code >= 400 or str(data.get("status") or "").lower() == "error":
        raise HTTPException(502, f"Bland rejected the call: {data.get('message') or response.status_code}")
    return {
        "provider_reference": data.get("call_id"),
        "provider_status": data.get("status") or "queued",
        "provider_response": {k: data.get(k) for k in ("status", "message", "call_id", "batch_id")},
    }


@router.post("/requests/{request_id}/dispatch")
async def dispatch_outbound_request(
    request_id: int,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    request = db.get(OutboundRequest, request_id)
    if not request or request.organization_id != principal.organization_id:
        raise HTTPException(404, "Outbound request not found")
    if request.status in {"queued", "sent", "completed"}:
        return {"request_id": request.id, "status": request.status, "provider_reference": request.provider_reference}
    if not _approved(db, request.id):
        raise HTTPException(409, "Owner approval is required before dispatch")

    lead = db.get(Lead, request.lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    decision = _decision_for_request(
        db, principal, request.lead_id, request.compliance_decision_id, request.channel, request.contact
    )
    suppression = _active_suppression(db, principal, request.channel, request.contact)
    if suppression:
        raise HTTPException(422, "Contact became suppressed after approval; dispatch blocked")

    if request.channel in VOICE_CHANNELS:
        # Enforced here rather than only at /voice/preflight. Preflight is
        # advisory -- nothing obliges a caller to run it -- so a script that
        # never says it is a machine would otherwise dial anyway. The FCC
        # treats an AI voice as an artificial voice, which is the difference
        # between a marketing call and a TCPA claim per call.
        problems = validate_call_script(_opening_line(request), _call_state(db, request), _will_record(request))
        if problems:
            raise HTTPException(422, f"Call script rejected: {', '.join(problems)}")

    try:
        result = await (_dispatch_twilio(request) if request.provider == "twilio" else _dispatch_bland(request))
        request.status = "queued"
        request.provider_reference = result["provider_reference"]
        request.provider_status = result["provider_status"]
        request.provider_response = result["provider_response"]
        request.dispatched_by_user_id = principal.user_id
        request.dispatched_at = datetime.now(timezone.utc)
        request.error = None
        if request.channel == "sms":
            # Written here because this is where a message actually goes out.
            # The frequency cap counts these rows, so a send the log never sees
            # is a send the cap cannot count, and the limit silently becomes no
            # limit at all.
            db.add(SmsMessage(
                organization_id=principal.organization_id,
                lead_id=request.lead_id,
                direction="outbound",
                contact=request.contact,
                body=str(request.content.get("body") or ""),
                decision_id=decision.id,
                status="queued",
                provider_message_id=request.provider_reference,
                evidence={"request_id": request.id, "provider": request.provider},
            ))
        if request.channel in VOICE_CHANNELS:
            # What was disclosed is recorded per call, at the moment of the
            # call. Deriving it from settings later would let a settings change
            # rewrite what a past call is able to claim.
            db.add(VoiceCall(
                organization_id=principal.organization_id,
                lead_id=request.lead_id,
                direction="outbound",
                contact=request.contact,
                state=_call_state(db, request),
                provider=request.provider,
                provider_call_id=request.provider_reference,
                decision_id=decision.id,
                status="queued",
                ai_disclosed=discloses_ai(_opening_line(request)),
                recorded=_will_record(request),
                recording_consent_basis=None,
                evidence={"request_id": request.id, "channel": request.channel},
            ))
        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            lead_id=request.lead_id,
            activity_type="outbound_dispatched",
            summary=f"{request.channel} dispatched via {request.provider} for {lead.seller_name}",
            metadata_json={
                "request_id": request.id,
                "compliance_decision_id": decision.id,
                "provider_reference": request.provider_reference,
            },
        ))
        db.commit()
    except HTTPException as exc:
        request.status = "failed"
        request.error = str(exc.detail)
        db.commit()
        raise

    return {
        "request_id": request.id,
        "status": request.status,
        "provider": request.provider,
        "provider_reference": request.provider_reference,
        "provider_status": request.provider_status,
    }


@router.get("/requests")
def list_outbound_requests(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    items = db.scalars(select(OutboundRequest).where(
        OutboundRequest.organization_id == principal.organization_id,
    ).order_by(OutboundRequest.created_at.desc()).limit(100)).all()
    return [{
        "id": item.id,
        "lead_id": item.lead_id,
        "channel": item.channel,
        "provider": item.provider,
        "contact": item.contact,
        "status": item.status,
        "provider_reference": item.provider_reference,
        "provider_status": item.provider_status,
        "error": item.error,
        "created_at": item.created_at,
        "dispatched_at": item.dispatched_at,
    } for item in items]

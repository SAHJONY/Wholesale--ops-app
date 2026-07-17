import os
from datetime import datetime, timedelta

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

router = APIRouter(prefix="/outbound", tags=["controlled outbound gateway"])

DECISION_TTL = timedelta(minutes=15)


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
    if datetime.utcnow() - decision.created_at > DECISION_TTL:
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
    from_number = os.getenv("TWILIO_FROM_NUMBER") or os.getenv("BLAND_DEFAULT_FROM_NUMBER")
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
        default_from = os.getenv("BLAND_DEFAULT_FROM_NUMBER") or os.getenv("BLAND_DEFAULT_CALLER_ID")
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

    try:
        result = await (_dispatch_twilio(request) if request.provider == "twilio" else _dispatch_bland(request))
        request.status = "queued"
        request.provider_reference = result["provider_reference"]
        request.provider_status = result["provider_status"]
        request.provider_response = result["provider_response"]
        request.dispatched_by_user_id = principal.user_id
        request.dispatched_at = datetime.utcnow()
        request.error = None
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

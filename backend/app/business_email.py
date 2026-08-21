"""Permanent SAHJONY departmental business-email transport.

Resend is the application transport.  The module is deliberately fail-closed:
no message leaves the application unless the API key is configured and the
selected sender belongs to the approved sahjony.com department map.
Inbound messages are accepted only after Svix signature verification and are
written into the CRM activity stream so a reply can be associated with a deal
or lead by the stable subject tags produced by outbound mail.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity
from .database import get_db
from .models import Deal, Lead

router = APIRouter(prefix="/business-email", tags=["business email"])

RESEND_API = "https://api.resend.com"
DEAL_TAG = re.compile(r"\[Deal\s+#(\d+)\]", re.IGNORECASE)
LEAD_TAG = re.compile(r"\[Lead\s+#(\d+)\]", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

FALLBACK_DEPARTMENTS = {
    "acquisitions": ("SAHJONY Acquisitions", "acquisitions@sahjony.com"),
    "dispositions": ("SAHJONY Dispositions", "dispositions@sahjony.com"),
    "title_closing": ("SAHJONY Title & Closing", "title@sahjony.com"),
    "underwriting": ("SAHJONY Underwriting", "underwriting@sahjony.com"),
    "compliance": ("SAHJONY Compliance", "compliance@sahjony.com"),
    "operations": ("SAHJONY Operations", "operations@sahjony.com"),
    "support": ("SAHJONY Support", "support@sahjony.com"),
    "executive": ("SAHJONY Executive Office", "executive@sahjony.com"),
}


def _department_config() -> dict[str, tuple[str, str]]:
    config_path = Path(__file__).resolve().parents[2] / "config" / "business-email-departments.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        return {
            key: (str(value["display_name"]), str(value["email"]).lower())
            for key, value in payload.get("departments", {}).items()
        } or FALLBACK_DEPARTMENTS
    except (OSError, ValueError, KeyError, TypeError):
        return FALLBACK_DEPARTMENTS


def _api_key() -> str:
    value = str(os.getenv("RESEND_API_KEY") or "").strip()
    if not value:
        raise HTTPException(503, "Business email is not live: RESEND_API_KEY is not configured")
    return value


def _default_org_id() -> int:
    raw = str(os.getenv("EMAIL_DEFAULT_ORGANIZATION_ID") or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise HTTPException(503, "Business email inbound routing is not live: EMAIL_DEFAULT_ORGANIZATION_ID is not configured")
    return int(raw)


def _sender_for(department: str) -> tuple[str, str]:
    departments = _department_config()
    selected = departments.get(department)
    if not selected:
        raise HTTPException(422, f"Unknown business-email department: {department}")
    display_name, email = selected
    if not email.endswith("@sahjony.com"):
        raise HTTPException(503, "Business email sender rejected by permanent domain policy")
    return display_name, email


def _tag_subject(subject: str, deal_id: int | None, lead_id: int | None) -> str:
    clean = subject.strip()
    if deal_id and not DEAL_TAG.search(clean):
        clean = f"[Deal #{deal_id}] {clean}"
    elif lead_id and not LEAD_TAG.search(clean):
        clean = f"[Lead #{lead_id}] {clean}"
    return clean


def _entity_ids(subject: str) -> tuple[int | None, int | None]:
    deal_match = DEAL_TAG.search(subject or "")
    lead_match = LEAD_TAG.search(subject or "")
    return (
        int(deal_match.group(1)) if deal_match else None,
        int(lead_match.group(1)) if lead_match else None,
    )


def _department_from_recipients(recipients: list[str]) -> str:
    by_email = {email: key for key, (_, email) in _department_config().items()}
    for item in recipients:
        normalized = str(item).strip().lower()
        if normalized in by_email:
            return by_email[normalized]
    return "support"


@router.get("/readiness")
def email_readiness(principal: Principal = Depends(require_role("viewer"))):
    del principal
    departments = _department_config()
    required = {
        "RESEND_API_KEY": bool(os.getenv("RESEND_API_KEY")),
        "RESEND_WEBHOOK_SECRET": bool(os.getenv("RESEND_WEBHOOK_SECRET")),
        "EMAIL_DEFAULT_ORGANIZATION_ID": bool(os.getenv("EMAIL_DEFAULT_ORGANIZATION_ID")),
        "EMAIL_DOMAIN_VERIFIED": str(os.getenv("EMAIL_DOMAIN_VERIFIED") or "").lower() == "true",
        "EMAIL_INBOUND_VERIFIED": str(os.getenv("EMAIL_INBOUND_VERIFIED") or "").lower() == "true",
    }
    return {
        "provider": "resend",
        "domain": "sahjony.com",
        "default_department": "acquisitions",
        "default_sender": departments["acquisitions"][1],
        "departments": {key: email for key, (_, email) in departments.items()},
        "checks": required,
        "sending_live": required["RESEND_API_KEY"] and required["EMAIL_DOMAIN_VERIFIED"],
        "responding_live": all(required.values()),
        "fail_closed": True,
    }


@router.post("/send")
async def send_business_email(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Send a business email from the approved departmental identity.

    This endpoint is intentionally an authenticated manager action.  It does
    not replace seller-contact compliance/approval gates elsewhere in the OS;
    callers must provide an authorization_basis documenting why this send is
    permitted.
    """
    department = str(payload.get("department") or "acquisitions").strip().lower()
    display_name, sender = _sender_for(department)
    recipients = payload.get("to")
    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [str(item).strip() for item in (recipients or []) if str(item).strip()]
    if not recipients or any(not EMAIL_RE.match(item) for item in recipients):
        raise HTTPException(422, "At least one valid recipient email is required")

    authorization_basis = str(payload.get("authorization_basis") or "").strip()
    if not authorization_basis:
        raise HTTPException(422, "authorization_basis is required; email transport does not bypass outreach/compliance gates")

    deal_id = int(payload["deal_id"]) if payload.get("deal_id") else None
    lead_id = int(payload["lead_id"]) if payload.get("lead_id") else None
    if deal_id and not db.get(Deal, deal_id):
        raise HTTPException(404, "Deal not found")
    if lead_id and not db.get(Lead, lead_id):
        raise HTTPException(404, "Lead not found")

    subject = _tag_subject(str(payload.get("subject") or "").strip(), deal_id, lead_id)
    text = str(payload.get("text") or "").strip()
    html = str(payload.get("html") or "").strip()
    if not subject or not (text or html):
        raise HTTPException(422, "subject and text or html body are required")

    body: dict[str, Any] = {
        "from": f"{display_name} <{sender}>",
        "to": recipients,
        "subject": subject,
        "reply_to": sender,
        "headers": {
            "X-SAHJONY-Department": department,
            "X-SAHJONY-Source": "wholesale-os",
        },
    }
    if text:
        body["text"] = text
    if html:
        body["html"] = html
    if deal_id:
        body["headers"]["X-SAHJONY-Deal-ID"] = str(deal_id)
    if lead_id:
        body["headers"]["X-SAHJONY-Lead-ID"] = str(lead_id)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{RESEND_API}/emails",
            headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
            json=body,
        )
    try:
        result = response.json()
    except ValueError:
        result = {"message": response.text[:1000]}
    if response.status_code >= 400:
        raise HTTPException(502, f"Email provider rejected send: {result.get('message') or response.status_code}")

    provider_id = str(result.get("id") or "")
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        deal_id=deal_id,
        activity_type="business_email_sent",
        summary=f"{department} email sent to {', '.join(recipients)}: {subject}",
        metadata_json={
            "provider": "resend",
            "provider_message_id": provider_id,
            "department": department,
            "from": sender,
            "to": recipients,
            "subject": subject,
            "authorization_basis": authorization_basis,
        },
    ))
    db.commit()
    return {
        "sent": True,
        "provider": "resend",
        "provider_message_id": provider_id,
        "department": department,
        "from": sender,
        "reply_to": sender,
        "to": recipients,
        "subject": subject,
        "deal_id": deal_id,
        "lead_id": lead_id,
    }


@router.post("/webhooks/resend")
async def resend_webhook(request: Request, db: Session = Depends(get_db)):
    """Accept verified Resend events and route inbound replies into CRM."""
    secret = str(os.getenv("RESEND_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise HTTPException(503, "RESEND_WEBHOOK_SECRET is not configured")

    raw = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id"),
        "svix-timestamp": request.headers.get("svix-timestamp"),
        "svix-signature": request.headers.get("svix-signature"),
    }
    if not all(headers.values()):
        raise HTTPException(400, "Missing Resend/Svix signature headers")
    try:
        from svix.webhooks import Webhook, WebhookVerificationError
        event = Webhook(secret).verify(raw, headers)
    except ImportError as exc:
        raise HTTPException(503, "svix dependency is unavailable") from exc
    except WebhookVerificationError as exc:
        raise HTTPException(401, "Invalid Resend webhook signature") from exc

    event_type = str(event.get("type") or "")
    event_data = event.get("data") or {}
    email_id = str(event_data.get("email_id") or "").strip()
    if not email_id:
        raise HTTPException(422, "Resend email.received event is missing email_id")

    event_id = str(headers["svix-id"])
    duplicate = db.scalar(select(CrmActivity).where(
        CrmActivity.activity_type.in_(["business_email_received", "business_email_status"]),
        CrmActivity.metadata_json["provider_event_id"].as_string() == event_id,
    ))
    if duplicate:
        return {"accepted": True, "duplicate": True, "activity_id": duplicate.id}

    if event_type != "email.received":
        tracked_types = {"email.sent", "email.delivered", "email.bounced", "email.complained", "email.suppressed"}
        if event_type not in tracked_types:
            return {"accepted": True, "ignored": True, "type": event_type}
        sent_rows = db.scalars(select(CrmActivity).where(
            CrmActivity.activity_type == "business_email_sent",
        ).order_by(CrmActivity.id.desc()).limit(500)).all()
        original = next((row for row in sent_rows if str((row.metadata_json or {}).get("provider_message_id") or "") == email_id), None)
        if not original:
            return {"accepted": True, "matched": False, "type": event_type}
        status = event_type.removeprefix("email.")
        db.add(CrmActivity(
            organization_id=original.organization_id,
            user_id=None,
            lead_id=original.lead_id,
            deal_id=original.deal_id,
            activity_type="business_email_status",
            summary=f"Business email {status}: {(original.metadata_json or {}).get('subject') or email_id}",
            metadata_json={
                "provider": "resend",
                "provider_event_id": event_id,
                "provider_email_id": email_id,
                "status": status,
                "department": (original.metadata_json or {}).get("department"),
            },
        ))
        db.commit()
        return {"accepted": True, "matched": True, "type": event_type, "status": status}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{RESEND_API}/emails/receiving/{email_id}",
            headers={"Authorization": f"Bearer {_api_key()}"},
        )
    try:
        email = response.json()
    except ValueError:
        email = {"message": response.text[:1000]}
    if response.status_code >= 400:
        raise HTTPException(502, f"Unable to retrieve inbound email: {email.get('message') or response.status_code}")

    subject = str(email.get("subject") or "")
    deal_id, lead_id = _entity_ids(subject)
    if deal_id and not db.get(Deal, deal_id):
        deal_id = None
    if lead_id and not db.get(Lead, lead_id):
        lead_id = None
    recipients = [str(item).lower() for item in (email.get("to") or [])]
    department = _department_from_recipients(recipients)
    sender = str(email.get("from") or "")
    preview = str(email.get("text") or "").strip()[:4000]

    activity = CrmActivity(
        organization_id=_default_org_id(),
        user_id=None,
        lead_id=lead_id,
        deal_id=deal_id,
        activity_type="business_email_received",
        summary=f"Inbound {department} email from {sender}: {subject}",
        metadata_json={
            "provider": "resend",
            "provider_event_id": event_id,
            "provider_email_id": email_id,
            "message_id": email.get("message_id"),
            "department": department,
            "from": sender,
            "to": email.get("to") or [],
            "cc": email.get("cc") or [],
            "subject": subject,
            "text_preview": preview,
            "has_html": bool(email.get("html")),
            "attachments": email.get("attachments") or [],
        },
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {
        "accepted": True,
        "activity_id": activity.id,
        "department": department,
        "deal_id": deal_id,
        "lead_id": lead_id,
        "from": sender,
        "subject": subject,
    }

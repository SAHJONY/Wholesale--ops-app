from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .compliance_models import ComplianceDecision, ContactConsent, ContactSuppression, DncCheck
from .crm import _assert_linked
from .database import get_db
from .models import Lead

router = APIRouter(prefix="/compliance", tags=["communication compliance"])

ALLOWED_CHANNELS = {"live_call", "automated_call", "sms", "email"}
CONSENT_REQUIRED = {"automated_call", "sms"}
CALL_CHANNELS = {"live_call", "automated_call"}
DNC_MAX_AGE_DAYS = 31
CALL_START_HOUR = 8
CALL_END_HOUR = 21


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return str(value or "").strip().lower()


def normalize_contact(channel: str, value: str) -> str:
    return normalize_phone(value) if channel != "email" else str(value or "").strip().lower()


def _active_suppression(db: Session, organization_id: int, channel: str, contact: str):
    channels = [channel]
    if channel in CALL_CHANNELS:
        channels.extend(["phone", "all"])
    elif channel == "sms":
        channels.extend(["phone", "all"])
    else:
        channels.append("all")
    return db.scalar(select(ContactSuppression).where(
        ContactSuppression.organization_id == organization_id,
        ContactSuppression.contact == contact,
        ContactSuppression.channel.in_(channels),
        ContactSuppression.active.is_(True),
    ).order_by(ContactSuppression.updated_at.desc()))


def _active_consent(db: Session, organization_id: int, channel: str, contact: str, now: datetime):
    consent = db.scalar(select(ContactConsent).where(
        ContactConsent.organization_id == organization_id,
        ContactConsent.contact == contact,
        ContactConsent.channel.in_([channel, "all"]),
        ContactConsent.status == "active",
    ).order_by(ContactConsent.captured_at.desc()))
    if not consent:
        return None
    if consent.expires_at and consent.expires_at <= now:
        return None
    return consent


def _latest_dnc(db: Session, organization_id: int, phone: str):
    return db.scalar(select(DncCheck).where(
        DncCheck.organization_id == organization_id,
        DncCheck.phone == phone,
    ).order_by(DncCheck.checked_at.desc()))


def evaluate_contact(db: Session, principal: Principal, lead: Lead, channel: str, contact: str,
                     recipient_timezone: str | None, requested_at: datetime | None = None) -> dict:
    if channel not in ALLOWED_CHANNELS:
        raise HTTPException(422, f"Unsupported channel: {channel}")
    if not lead.property:
        raise HTTPException(422, "Lead property is required for compliance evaluation")
    state = str(lead.property.state or "").upper()
    normalized = normalize_contact(channel, contact)
    now = requested_at or datetime.now(timezone.utc)
    reasons: list[str] = []
    evidence: dict = {"state": state, "policy": "fail_closed"}

    if state == "TX":
        reasons.append("texas_excluded")

    suppression = _active_suppression(db, principal.organization_id, channel, normalized)
    if suppression:
        reasons.append("entity_specific_suppression")
        evidence["suppression"] = {"reason": suppression.reason, "source": suppression.source}

    if channel in CALL_CHANNELS or channel == "sms":
        dnc = _latest_dnc(db, principal.organization_id, normalized)
        if not dnc:
            reasons.append("dnc_check_missing")
        else:
            age = now - dnc.checked_at
            evidence["dnc"] = {
                "checked_at": dnc.checked_at.isoformat(),
                "provider": dnc.provider,
                "national_dnc": dnc.national_dnc,
                "state_dnc": dnc.state_dnc,
                "age_days": age.days,
            }
            if age > timedelta(days=DNC_MAX_AGE_DAYS):
                reasons.append("dnc_check_stale")
            if dnc.national_dnc:
                reasons.append("national_dnc_match")
            if dnc.state_dnc:
                reasons.append("state_dnc_match")

    if channel in CONSENT_REQUIRED:
        consent = _active_consent(db, principal.organization_id, channel, normalized, now)
        if not consent:
            reasons.append("written_consent_missing")
        else:
            evidence["consent"] = {
                "type": consent.consent_type,
                "captured_at": consent.captured_at.isoformat(),
                "source": consent.source,
            }

    if channel in CALL_CHANNELS:
        if not recipient_timezone:
            reasons.append("recipient_timezone_missing")
        else:
            try:
                local_time = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(recipient_timezone))
                evidence["recipient_local_time"] = local_time.isoformat()
                if not (CALL_START_HOUR <= local_time.hour < CALL_END_HOUR):
                    reasons.append("outside_calling_hours")
            except ZoneInfoNotFoundError:
                reasons.append("recipient_timezone_invalid")

    allowed = not reasons
    decision = ComplianceDecision(
        organization_id=principal.organization_id,
        lead_id=lead.id,
        channel=channel,
        contact=normalized,
        allowed=allowed,
        reasons=reasons,
        evidence=evidence,
        requested_by_user_id=principal.user_id,
    )
    db.add(decision)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="compliance_decision",
        summary=f"{channel} compliance {'allowed' if allowed else 'blocked'} for {lead.seller_name}",
        metadata_json={"contact": normalized, "allowed": allowed, "reasons": reasons, "evidence": evidence},
    ))
    db.commit()
    return {
        "decision_id": decision.id,
        "lead_id": lead.id,
        "channel": channel,
        "contact": normalized,
        "allowed": allowed,
        "reasons": reasons,
        "evidence": evidence,
        "expires_at": (now + timedelta(minutes=15)).isoformat() if allowed else None,
    }


@router.post("/evaluate")
def evaluate(payload: dict, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_id = int(payload.get("lead_id") or 0)
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    channel = str(payload.get("channel") or "").strip().lower()
    contact = str(payload.get("contact") or "").strip()
    if not contact:
        contact = lead.email if channel == "email" else lead.phone
    if not contact:
        raise HTTPException(422, "Contact is required")
    return evaluate_contact(db, principal, lead, channel, contact, payload.get("recipient_timezone"))


@router.post("/suppressions")
def create_suppression(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    channel = str(payload.get("channel") or "all").strip().lower()
    contact = normalize_contact(channel, str(payload.get("contact") or ""))
    if not contact:
        raise HTTPException(422, "Contact is required")
    record = db.scalar(select(ContactSuppression).where(
        ContactSuppression.organization_id == principal.organization_id,
        ContactSuppression.channel == channel,
        ContactSuppression.contact == contact,
    ))
    if not record:
        record = ContactSuppression(
            organization_id=principal.organization_id,
            lead_id=payload.get("lead_id"),
            channel=channel,
            contact=contact,
            reason=str(payload.get("reason") or "entity_specific_request"),
            source=str(payload.get("source") or "manual"),
            notes=payload.get("notes"),
            active=True,
        )
        db.add(record)
    else:
        record.active = True
        record.reason = str(payload.get("reason") or record.reason)
        record.source = str(payload.get("source") or record.source)
        record.notes = payload.get("notes", record.notes)
    db.commit()
    return {"id": record.id, "active": record.active, "channel": record.channel, "contact": record.contact}


@router.post("/consents")
def record_consent(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    channel = str(payload.get("channel") or "").strip().lower()
    if channel not in CONSENT_REQUIRED | {"email", "live_call", "all"}:
        raise HTTPException(422, "Unsupported consent channel")
    contact = normalize_contact(channel, str(payload.get("contact") or ""))
    source = str(payload.get("source") or "").strip()
    if not contact or not source:
        raise HTTPException(422, "Contact and consent source are required")
    record = ContactConsent(
        organization_id=principal.organization_id,
        lead_id=payload.get("lead_id"),
        channel=channel,
        contact=contact,
        consent_type=str(payload.get("consent_type") or "prior_express_written_consent"),
        status="active",
        source=source,
        evidence=payload.get("evidence") or {},
    )
    db.add(record)
    db.commit()
    return {"id": record.id, "status": record.status, "channel": record.channel, "contact": record.contact}


@router.post("/dnc-checks")
def record_dnc_check(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    phone = normalize_phone(str(payload.get("phone") or ""))
    provider = str(payload.get("provider") or "").strip()
    if not phone or not provider:
        raise HTTPException(422, "Phone and provider are required")
    record = DncCheck(
        organization_id=principal.organization_id,
        lead_id=payload.get("lead_id"),
        phone=phone,
        national_dnc=bool(payload.get("national_dnc", False)),
        state_dnc=bool(payload.get("state_dnc", False)),
        provider=provider,
        raw_reference=payload.get("raw_reference") or {},
    )
    db.add(record)
    db.commit()
    return {"id": record.id, "phone": record.phone, "national_dnc": record.national_dnc, "state_dnc": record.state_dnc}


@router.get("/decisions")
def decisions(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(ComplianceDecision).where(
        ComplianceDecision.organization_id == principal.organization_id,
    ).order_by(ComplianceDecision.created_at.desc()).limit(100)).all()
    return [{
        "id": row.id,
        "lead_id": row.lead_id,
        "channel": row.channel,
        "contact": row.contact,
        "allowed": row.allowed,
        "reasons": row.reasons,
        "evidence": row.evidence,
        "created_at": row.created_at,
    } for row in rows]

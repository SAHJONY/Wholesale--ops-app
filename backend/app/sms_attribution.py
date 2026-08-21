from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .database import get_db
from .models import Lead
from .sms_agentic_models import SmsConversationState
from .sms_attribution_models import SmsAttributionEvent
from .sms_campaign_models import SmsCampaign, SmsCampaignRecipient
from .sms_models import SmsMessage
from .sms_scheduling_models import SmsAppointmentRequest

router = APIRouter(prefix="/sms-attribution", tags=["SAHJONY SMS attribution"])

MILESTONES = frozenset({
    "offer_created", "offer_accepted", "contract_signed", "assignment_closed", "assignment_fee_received"
})
REALIZED_REVENUE_EVENT = "assignment_fee_received"


def _campaign(db: Session, principal: Principal, campaign_id: int) -> SmsCampaign:
    row = db.get(SmsCampaign, campaign_id)
    if not row or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Campaign not found")
    return row


def _amount(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, "amount must be numeric") from exc
    if amount < 0:
        raise HTTPException(422, "amount cannot be negative")
    return amount


def _realized_revenue(events: list[SmsAttributionEvent]) -> Decimal:
    return sum(
        (Decimal(str(event.amount)) for event in events
         if event.event_type == REALIZED_REVENUE_EVENT and event.amount is not None),
        Decimal("0"),
    )


@router.post("/events")
def record_event(
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    event_type = str(payload.get("event_type") or "").strip().lower()
    if event_type not in MILESTONES:
        raise HTTPException(422, f"event_type must be one of: {', '.join(sorted(MILESTONES))}")
    lead_id = int(payload.get("lead_id") or 0)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    campaign_id = int(payload.get("campaign_id") or 0) or None
    if campaign_id:
        _campaign(db, principal, campaign_id)
        linked = db.scalar(select(SmsCampaignRecipient.id).where(
            SmsCampaignRecipient.organization_id == principal.organization_id,
            SmsCampaignRecipient.campaign_id == campaign_id,
            SmsCampaignRecipient.lead_id == lead_id,
        ))
        if not linked:
            raise HTTPException(409, "Lead is not attributed to this campaign")
    else:
        recipient = db.scalar(select(SmsCampaignRecipient).where(
            SmsCampaignRecipient.organization_id == principal.organization_id,
            SmsCampaignRecipient.lead_id == lead_id,
        ).order_by(SmsCampaignRecipient.created_at.desc()))
        campaign_id = recipient.campaign_id if recipient else None

    reference = str(payload.get("reference") or "").strip() or None
    if reference:
        existing = db.scalar(select(SmsAttributionEvent).where(
            SmsAttributionEvent.organization_id == principal.organization_id,
            SmsAttributionEvent.event_type == event_type,
            SmsAttributionEvent.reference == reference,
        ))
        if existing:
            return {"id": existing.id, "duplicate": True, "campaign_id": existing.campaign_id, "lead_id": existing.lead_id}

    row = SmsAttributionEvent(
        organization_id=principal.organization_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        event_type=event_type,
        amount=_amount(payload.get("amount")),
        source=str(payload.get("source") or "manual_or_system").strip()[:60],
        reference=reference,
        note=str(payload.get("note") or "").strip() or None,
        metadata_json=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        created_by_user_id=principal.user_id,
    )
    db.add(row)
    db.flush()
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        activity_type="sms_attribution_milestone",
        summary=f"SAHJONY SMS attribution milestone: {event_type}",
        metadata_json={"event_id": row.id, "campaign_id": campaign_id, "amount": str(row.amount) if row.amount is not None else None},
    ))
    db.commit()
    return {"id": row.id, "campaign_id": campaign_id, "lead_id": lead_id, "event_type": event_type, "amount": float(row.amount) if row.amount is not None else None}


@router.get("/campaigns/{campaign_id}")
def campaign_funnel(
    campaign_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    campaign = _campaign(db, principal, campaign_id)
    recipients = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
    )).all()
    lead_ids = {row.lead_id for row in recipients}
    sent_leads = {row.lead_id for row in recipients if row.status == "dispatched"}

    replies: set[int] = set()
    qualified: set[int] = set()
    booked: set[int] = set()
    if lead_ids:
        replies = set(db.scalars(select(SmsMessage.lead_id).where(
            SmsMessage.organization_id == principal.organization_id,
            SmsMessage.lead_id.in_(lead_ids),
            SmsMessage.direction == "inbound",
        )).all())
        qualified = set(db.scalars(select(SmsConversationState.lead_id).where(
            SmsConversationState.organization_id == principal.organization_id,
            SmsConversationState.lead_id.in_(lead_ids),
            SmsConversationState.stage.in_(["qualified", "appointment_ready", "negotiating"]),
        )).all())
        booked = set(db.scalars(select(SmsAppointmentRequest.lead_id).where(
            SmsAppointmentRequest.organization_id == principal.organization_id,
            SmsAppointmentRequest.lead_id.in_(lead_ids),
            SmsAppointmentRequest.status == "booked",
        )).all())

    events = db.scalars(select(SmsAttributionEvent).where(
        SmsAttributionEvent.organization_id == principal.organization_id,
        SmsAttributionEvent.campaign_id == campaign.id,
    )).all()
    by_type: dict[str, set[int]] = {key: set() for key in MILESTONES}
    for event in events:
        by_type.setdefault(event.event_type, set()).add(event.lead_id)
    revenue = _realized_revenue(events)

    audience = len(lead_ids)
    sent = len(sent_leads)
    replied = len(replies & lead_ids)
    appointments = len(booked & lead_ids)
    contracted = len(by_type.get("contract_signed", set()))
    closed = len(by_type.get("assignment_closed", set()) | by_type.get("assignment_fee_received", set()))

    def rate(numerator: int, denominator: int) -> float:
        return round((numerator / denominator) * 100, 2) if denominator else 0.0

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_status": campaign.status,
        "funnel": {
            "audience": audience,
            "sent": sent,
            "replied": replied,
            "qualified": len(qualified & lead_ids),
            "appointments_booked": appointments,
            "offers_created": len(by_type.get("offer_created", set())),
            "offers_accepted": len(by_type.get("offer_accepted", set())),
            "contracts_signed": contracted,
            "assignments_closed": closed,
        },
        "conversion": {
            "sent_rate": rate(sent, audience),
            "reply_rate": rate(replied, sent),
            "appointment_rate_from_reply": rate(appointments, replied),
            "contract_rate_from_sent": rate(contracted, sent),
            "close_rate_from_sent": rate(closed, sent),
        },
        "revenue": {
            "assignment_revenue": float(revenue),
            "revenue_per_sent": float(revenue / sent) if sent else 0.0,
            "revenue_per_closed": float(revenue / closed) if closed else 0.0,
            "recognized_from": REALIZED_REVENUE_EVENT,
        },
        "event_count": len(events),
    }


@router.get("/summary")
def portfolio_summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    campaigns = db.scalars(select(SmsCampaign).where(
        SmsCampaign.organization_id == principal.organization_id
    ).order_by(SmsCampaign.created_at.desc()).limit(100)).all()
    rows = []
    for campaign in campaigns:
        funnel = campaign_funnel(campaign.id, principal, db)
        rows.append({
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "status": campaign.status,
            **funnel["funnel"],
            **funnel["revenue"],
        })
    return {"campaigns": rows, "campaign_count": len(rows)}

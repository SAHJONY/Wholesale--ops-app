from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .autonomy import create_task
from .compliance import evaluate_contact
from .database import get_db
from .models import Lead
from .outbound_gateway import create_outbound_request
from .sms_campaign_execution import infer_recipient_timezone
from .sms_scheduling_models import SmsAppointmentRequest, SmsFollowUpJob

router = APIRouter(prefix="/sms-scheduling", tags=["SAHJONY SMS appointments and follow-up"])

MAX_FOLLOW_UP_DAYS = 90
MAX_DUE_BATCH = 25
ACTIVE_FOLLOW_UP_STATUSES = frozenset({"scheduled", "due", "pending_owner_approval"})


def parse_agent_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def cancel_active_followups(
    db: Session,
    organization_id: int,
    lead_id: int,
    reason: str,
    exclude_source_message_id: int | None = None,
) -> int:
    rows = db.scalars(select(SmsFollowUpJob).where(
        SmsFollowUpJob.organization_id == organization_id,
        SmsFollowUpJob.lead_id == lead_id,
        SmsFollowUpJob.status.in_(ACTIVE_FOLLOW_UP_STATUSES),
    )).all()
    cancelled = 0
    for row in rows:
        if exclude_source_message_id and row.source_message_id == exclude_source_message_id:
            continue
        row.status = "cancelled"
        row.cancellation_reason = reason[:180]
        cancelled += 1
    return cancelled


def schedule_from_agent(
    db: Session,
    principal: Principal,
    lead: Lead,
    conversation_state_id: int | None,
    source_message_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Persist appointment/follow-up intent extracted from a seller turn.

    This function never creates a calendar event and never sends a message.
    It only creates auditable work records. Calendar booking and outbound SMS
    remain separate execution steps.
    """
    cancelled = cancel_active_followups(
        db, principal.organization_id, lead.id, "seller_replied", exclude_source_message_id=source_message_id
    )

    appointment_id = None
    appointment_at = parse_agent_datetime(result.get("appointment_at_iso"))
    appointment_timezone = str(result.get("appointment_timezone") or "").strip() or None
    appointment_confidence = int(max(0, min(100, int(result.get("appointment_confidence") or 0))))
    qualification = result.get("qualification") if isinstance(result.get("qualification"), dict) else {}
    raw_preference = qualification.get("appointment_preference")

    wants_appointment = result.get("next_action") in {"book_appointment", "prepare_call"} or result.get("intent") in {
        "appointment", "call_request"
    }
    if wants_appointment:
        status = "ready_to_book" if appointment_at and appointment_timezone and appointment_confidence >= 80 else "needs_confirmation"
        appointment = SmsAppointmentRequest(
            organization_id=principal.organization_id,
            lead_id=lead.id,
            conversation_state_id=conversation_state_id,
            source_message_id=source_message_id,
            status=status,
            requested_start_at=appointment_at,
            recipient_timezone=appointment_timezone,
            duration_minutes=30,
            raw_preference=str(raw_preference or "").strip() or None,
            confidence=appointment_confidence,
            metadata_json={
                "intent": result.get("intent"),
                "next_action": result.get("next_action"),
                "source": result.get("source"),
                "extraction_policy": "explicit_datetime_only",
            },
        )
        db.add(appointment)
        db.flush()
        appointment_id = appointment.id
        create_task(
            db,
            "seller_appointment_booking" if status == "ready_to_book" else "seller_appointment_confirmation",
            {
                "appointment_request_id": appointment.id,
                "requested_start_at": appointment_at.isoformat() if appointment_at else None,
                "recipient_timezone": appointment_timezone,
                "confidence": appointment_confidence,
                "raw_preference": raw_preference,
            },
            priority=100 if status == "ready_to_book" else 90,
            lead_id=lead.id,
            requires_approval=status != "ready_to_book",
        )

    follow_up_id = None
    follow_up_days = result.get("follow_up_days")
    follow_up_draft = str(result.get("follow_up_draft") or "").strip()
    if follow_up_days not in (None, "") and follow_up_draft:
        try:
            days = int(follow_up_days)
        except (TypeError, ValueError):
            days = 0
        if 1 <= days <= MAX_FOLLOW_UP_DAYS and result.get("intent") not in {
            "opt_out", "wrong_number", "hostile", "not_interested"
        }:
            inferred_timezone, timezone_source = infer_recipient_timezone(lead, appointment_timezone)
            follow_up = SmsFollowUpJob(
                organization_id=principal.organization_id,
                lead_id=lead.id,
                conversation_state_id=conversation_state_id,
                source_message_id=source_message_id,
                due_at=datetime.now(timezone.utc) + timedelta(days=days),
                recipient_timezone=inferred_timezone,
                reason="agent_recommended_follow_up",
                body_draft=follow_up_draft,
                status="scheduled" if inferred_timezone else "needs_timezone",
                metadata_json={
                    "follow_up_days": days,
                    "timezone_source": timezone_source,
                    "source": result.get("source"),
                    "next_action": result.get("next_action"),
                },
            )
            db.add(follow_up)
            db.flush()
            follow_up_id = follow_up.id

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="sms_scheduling_updated",
        summary=f"SMS scheduling updated: appointment={appointment_id or 'none'}, follow_up={follow_up_id or 'none'}",
        metadata_json={
            "appointment_request_id": appointment_id,
            "follow_up_job_id": follow_up_id,
            "cancelled_prior_followups": cancelled,
        },
    ))
    return {
        "appointment_request_id": appointment_id,
        "follow_up_job_id": follow_up_id,
        "cancelled_prior_followups": cancelled,
    }


@router.get("/summary")
def summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    appointments = db.scalars(select(SmsAppointmentRequest).where(
        SmsAppointmentRequest.organization_id == principal.organization_id
    )).all()
    followups = db.scalars(select(SmsFollowUpJob).where(
        SmsFollowUpJob.organization_id == principal.organization_id
    )).all()
    counts: dict[str, int] = {}
    for row in appointments:
        counts[f"appointment_{row.status}"] = counts.get(f"appointment_{row.status}", 0) + 1
    for row in followups:
        counts[f"followup_{row.status}"] = counts.get(f"followup_{row.status}", 0) + 1
    return counts


@router.get("/appointments")
def appointments(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(SmsAppointmentRequest).where(
        SmsAppointmentRequest.organization_id == principal.organization_id
    ).order_by(SmsAppointmentRequest.created_at.desc()).limit(200)).all()
    return [{
        "id": row.id,
        "lead_id": row.lead_id,
        "status": row.status,
        "requested_start_at": row.requested_start_at,
        "recipient_timezone": row.recipient_timezone,
        "duration_minutes": row.duration_minutes,
        "raw_preference": row.raw_preference,
        "confidence": row.confidence,
        "provider": row.provider,
        "calendar_event_id": row.calendar_event_id,
    } for row in rows]


@router.post("/appointments/{appointment_id}/booked")
def mark_appointment_booked(
    appointment_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    row = db.get(SmsAppointmentRequest, appointment_id)
    if not row or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Appointment request not found")
    event_id = str(payload.get("calendar_event_id") or "").strip()
    provider = str(payload.get("provider") or "google_calendar").strip()
    if not event_id:
        raise HTTPException(422, "calendar_event_id is required")
    row.status = "booked"
    row.provider = provider
    row.calendar_event_id = event_id
    cancel_active_followups(db, principal.organization_id, row.lead_id, "appointment_booked")
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=row.lead_id,
        activity_type="seller_appointment_booked",
        summary=f"Seller appointment booked via {provider}",
        metadata_json={"appointment_request_id": row.id, "calendar_event_id": event_id},
    ))
    db.commit()
    return {"id": row.id, "status": row.status, "provider": provider, "calendar_event_id": event_id}


@router.get("/follow-ups")
def follow_ups(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(SmsFollowUpJob).where(
        SmsFollowUpJob.organization_id == principal.organization_id
    ).order_by(SmsFollowUpJob.due_at.asc()).limit(300)).all()
    return [{
        "id": row.id,
        "lead_id": row.lead_id,
        "due_at": row.due_at,
        "recipient_timezone": row.recipient_timezone,
        "reason": row.reason,
        "body_draft": row.body_draft,
        "status": row.status,
        "cancellation_reason": row.cancellation_reason,
        "outbound_request_id": row.outbound_request_id,
    } for row in rows]


@router.post("/follow-ups/prepare-due")
def prepare_due_followups(
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Prepare due follow-ups for owner approval; never dispatch from this endpoint."""
    limit = max(1, min(int(payload.get("limit") or 10), MAX_DUE_BATCH))
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(SmsFollowUpJob).where(
        SmsFollowUpJob.organization_id == principal.organization_id,
        SmsFollowUpJob.status == "scheduled",
        SmsFollowUpJob.due_at <= now,
    ).order_by(SmsFollowUpJob.due_at.asc()).limit(limit)).all()

    prepared = blocked = needs_timezone = 0
    results: list[dict[str, Any]] = []
    for row in rows:
        lead = db.get(Lead, row.lead_id)
        if not lead or not row.body_draft:
            row.status = "blocked"
            row.cancellation_reason = "lead_or_body_missing"
            blocked += 1
            continue
        if not row.recipient_timezone:
            row.status = "needs_timezone"
            needs_timezone += 1
            continue
        contact = str(lead.phone or "").strip()
        if not contact:
            row.status = "blocked"
            row.cancellation_reason = "lead_phone_missing"
            blocked += 1
            continue
        decision = evaluate_contact(db, principal, lead, "sms", contact, row.recipient_timezone)
        if not decision["allowed"]:
            row.status = "blocked"
            row.cancellation_reason = ",".join(decision.get("reasons") or []) or "compliance_blocked"
            blocked += 1
            db.commit()
            continue
        result = create_outbound_request({
            "lead_id": lead.id,
            "channel": "sms",
            "provider": "bland",
            "contact": contact,
            "compliance_decision_id": decision["decision_id"],
            "content": {
                "body": row.body_draft,
                "new_conversation": False,
                "metadata": {
                    "follow_up_job_id": row.id,
                    "brand": "SAHJONY AI Acquisition",
                },
                "request_data": {"follow_up_job_id": row.id},
            },
        }, principal, db)
        row.outbound_request_id = result["request_id"]
        row.status = "pending_owner_approval"
        row.metadata_json = {
            **(row.metadata_json or {}),
            "compliance_decision_id": decision["decision_id"],
            "approval_id": result["approval_id"],
            "prepared_at": now.isoformat(),
        }
        prepared += 1
        results.append({
            "follow_up_job_id": row.id,
            "outbound_request_id": result["request_id"],
            "approval_id": result["approval_id"],
        })
        db.commit()

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="sms_followups_prepared",
        summary=f"Prepared {prepared} due seller follow-ups for owner approval",
        metadata_json={"prepared": prepared, "blocked": blocked, "needs_timezone": needs_timezone},
    ))
    db.commit()
    return {
        "evaluated": len(rows),
        "pending_owner_approval": prepared,
        "blocked": blocked,
        "needs_timezone": needs_timezone,
        "results": results,
        "messages_sent": 0,
    }

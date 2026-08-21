from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .database import get_db
from .models import Lead
from .sms_scheduling import cancel_active_followups
from .sms_scheduling_models import SmsAppointmentRequest

router = APIRouter(prefix="/sms-calendar", tags=["SAHJONY seller Google Calendar"])

TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"


def calendar_id() -> str:
    return str(os.getenv("GOOGLE_CALENDAR_ID") or "primary").strip() or "primary"


def google_calendar_configured() -> bool:
    return all(str(os.getenv(name) or "").strip() for name in (
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_CALENDAR_REFRESH_TOKEN",
    ))


async def _access_token() -> str:
    client_id = str(os.getenv("GOOGLE_CALENDAR_CLIENT_ID") or "").strip()
    client_secret = str(os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET") or "").strip()
    refresh_token = str(os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise HTTPException(503, "Google Calendar OAuth is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    try:
        payload = response.json()
    except ValueError:
        payload = {"error_description": response.text[:500]}
    token = str(payload.get("access_token") or "").strip()
    if response.status_code >= 400 or not token:
        detail = payload.get("error_description") or payload.get("error") or response.status_code
        raise HTTPException(502, f"Google Calendar OAuth refresh failed: {detail}")
    return token


async def _calendar_is_free(access_token: str, start_at: datetime, end_at: datetime) -> bool:
    cid = calendar_id()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{CALENDAR_API}/freeBusy",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={
                "timeMin": start_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "timeMax": end_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "timeZone": "UTC",
                "items": [{"id": cid}],
            },
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        raise HTTPException(502, f"Google Calendar free/busy lookup failed: {response.status_code}")
    calendar_state = (payload.get("calendars") or {}).get(cid) or {}
    if calendar_state.get("errors"):
        raise HTTPException(502, "Google Calendar free/busy lookup returned a calendar error")
    return not bool(calendar_state.get("busy") or [])


def _local_event_time(value: datetime, timezone_name: str) -> dict:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(422, "Appointment timezone is invalid") from exc
    return {"dateTime": value.astimezone(zone).isoformat(), "timeZone": timezone_name}


async def _insert_event(
    access_token: str,
    appointment: SmsAppointmentRequest,
    lead: Lead,
) -> dict:
    if not appointment.requested_start_at or not appointment.recipient_timezone:
        raise HTTPException(422, "Appointment requires a resolved start time and timezone")
    start_at = appointment.requested_start_at
    end_at = start_at + timedelta(minutes=max(10, min(int(appointment.duration_minutes or 30), 180)))
    prop = lead.property
    address = getattr(prop, "address", None) if prop else None
    summary = f"SAHJONY Seller Call — {lead.seller_name or f'Lead {lead.id}'}"
    description_lines = [
        "SAHJONY AI Acquisition seller appointment",
        f"Lead ID: {lead.id}",
        f"Appointment request ID: {appointment.id}",
    ]
    if address:
        description_lines.append(f"Property: {address}")
    if appointment.raw_preference:
        description_lines.append(f"Seller requested: {appointment.raw_preference}")

    event = {
        "summary": summary,
        "description": "\n".join(description_lines),
        "start": _local_event_time(start_at, appointment.recipient_timezone),
        "end": _local_event_time(end_at, appointment.recipient_timezone),
        "transparency": "opaque",
        "visibility": "private",
        "extendedProperties": {
            "private": {
                "sahjony_lead_id": str(lead.id),
                "sms_appointment_request_id": str(appointment.id),
                "source": "sahjony_ai_acquisition",
            }
        },
    }
    cid = calendar_id()
    url = f"{CALENDAR_API}/calendars/{quote(cid, safe='')}/events"
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            url,
            params={"sendUpdates": "none"},
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=event,
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:500]}
    if response.status_code >= 400 or not payload.get("id"):
        raise HTTPException(502, f"Google Calendar event creation failed: {payload.get('message') or response.status_code}")
    return payload


async def _delete_event(access_token: str, event_id: str) -> None:
    cid = calendar_id()
    url = f"{CALENDAR_API}/calendars/{quote(cid, safe='')}/events/{quote(event_id, safe='')}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.delete(
            url,
            params={"sendUpdates": "none"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code not in {200, 204, 404, 410}:
        raise HTTPException(502, f"Google Calendar event deletion failed: {response.status_code}")


@router.get("/health")
def health(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "provider": "google_calendar",
        "configured": google_calendar_configured(),
        "calendar_id_configured": bool(os.getenv("GOOGLE_CALENDAR_ID")),
        "oauth_mode": "offline_refresh_token",
    }


@router.post("/appointments/{appointment_id}/book")
async def book_appointment(
    appointment_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    appointment = db.get(SmsAppointmentRequest, appointment_id)
    if not appointment or appointment.organization_id != principal.organization_id:
        raise HTTPException(404, "Appointment request not found")
    if appointment.status == "booked" and appointment.calendar_event_id:
        return {
            "appointment_request_id": appointment.id,
            "status": "booked",
            "calendar_event_id": appointment.calendar_event_id,
            "idempotent": True,
        }
    if appointment.status != "ready_to_book":
        raise HTTPException(409, "Appointment is not ready to book; seller time confirmation is required")
    if not appointment.requested_start_at or not appointment.recipient_timezone:
        raise HTTPException(422, "Appointment start time and timezone are required")
    if appointment.requested_start_at <= datetime.now(timezone.utc):
        appointment.status = "needs_confirmation"
        db.commit()
        raise HTTPException(409, "Seller requested time is no longer in the future")

    lead = db.get(Lead, appointment.lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    duration = max(10, min(int((payload or {}).get("duration_minutes") or appointment.duration_minutes or 30), 180))
    appointment.duration_minutes = duration
    end_at = appointment.requested_start_at + timedelta(minutes=duration)

    token = await _access_token()
    if not await _calendar_is_free(token, appointment.requested_start_at, end_at):
        appointment.status = "calendar_conflict"
        appointment.metadata_json = {
            **(appointment.metadata_json or {}),
            "calendar_conflict_at": datetime.now(timezone.utc).isoformat(),
            "calendar_id": calendar_id(),
        }
        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            lead_id=lead.id,
            activity_type="seller_appointment_calendar_conflict",
            summary=f"Google Calendar conflict for seller appointment #{appointment.id}",
            metadata_json={"appointment_request_id": appointment.id},
        ))
        db.commit()
        raise HTTPException(409, "Requested seller time conflicts with the acquisition calendar")

    event = await _insert_event(token, appointment, lead)
    appointment.status = "booked"
    appointment.provider = "google_calendar"
    appointment.calendar_event_id = str(event["id"])
    appointment.metadata_json = {
        **(appointment.metadata_json or {}),
        "calendar_id": calendar_id(),
        "calendar_event_link": event.get("htmlLink"),
        "calendar_created_at": datetime.now(timezone.utc).isoformat(),
    }
    cancel_active_followups(db, principal.organization_id, lead.id, "appointment_booked")
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="seller_appointment_booked",
        summary=f"Seller appointment booked on Google Calendar for {lead.seller_name}",
        metadata_json={
            "appointment_request_id": appointment.id,
            "calendar_event_id": appointment.calendar_event_id,
            "requested_start_at": appointment.requested_start_at.isoformat(),
        },
    ))
    db.commit()
    return {
        "appointment_request_id": appointment.id,
        "status": appointment.status,
        "provider": appointment.provider,
        "calendar_event_id": appointment.calendar_event_id,
        "calendar_event_link": event.get("htmlLink"),
        "start_at": appointment.requested_start_at,
        "duration_minutes": appointment.duration_minutes,
    }


@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: int,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    appointment = db.get(SmsAppointmentRequest, appointment_id)
    if not appointment or appointment.organization_id != principal.organization_id:
        raise HTTPException(404, "Appointment request not found")
    event_id = str(appointment.calendar_event_id or "").strip()
    if event_id:
        token = await _access_token()
        await _delete_event(token, event_id)
    appointment.status = "cancelled"
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=appointment.lead_id,
        activity_type="seller_appointment_cancelled",
        summary=f"Seller appointment #{appointment.id} cancelled",
        metadata_json={"appointment_request_id": appointment.id, "calendar_event_id": event_id or None},
    ))
    db.commit()
    return {"appointment_request_id": appointment.id, "status": appointment.status}

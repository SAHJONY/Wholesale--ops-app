"""Bland.ai calls, and the two things voice needs that messaging does not.

Outbound dispatch already exists in ``outbound_gateway``, behind a compliance
decision and owner approval. This adds what an AI voice agent specifically
requires, plus the inbound side, which had no handler at all.

**Disclosure.** In February 2024 the FCC declared that AI-generated and cloned
voices in calls are "artificial voice" for TCPA purposes. That has two
consequences: calls to a mobile number need prior express *written* consent
rather than the ordinary kind, and the person answering should be told they are
talking to an automated system. So the opening line is checked for a
disclosure, and a call whose script does not contain one is refused.

**Recording.** Roughly a dozen states require every party to consent before a
call is recorded, and getting it wrong there is not a compliance ticket but a
criminal statute. Recording therefore stays off unless it is asked for, and
when it is asked for in an all-party state the opening line must announce it.
Florida is such a state, which matters here because Escambia County is the
first configured market.

**Verbal opt-out.** Asking to be taken off a list is a do-not-call request
whether it arrives by text or by voice, and the caller is under no obligation
to use a keyword. Inbound transcripts are scanned for that request and the
number is suppressed on the spot.

Nothing here dials. Placing a call stays with the outbound gateway.
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity
from .compliance import normalize_phone
from .database import get_db
from .sms_engine import suppress
from .voice_models import VoiceCall

router = APIRouter(prefix="/voice", tags=["bland.ai voice"])

# States requiring every party to consent before a call is recorded. Sources
# disagree at the margin -- Connecticut, Michigan and Nevada are argued either
# way -- so the contested ones are included. Over-disclosing costs a sentence
# of script; under-disclosing is a criminal exposure in several of these.
ALL_PARTY_CONSENT_STATES = frozenset({
    "CA", "CT", "DE", "FL", "IL", "MD", "MA", "MI", "MT", "NV", "NH", "OR", "PA", "WA",
})

# Phrases that count as telling someone they are speaking with a machine.
AI_DISCLOSURE_PATTERNS = (
    r"\bautomated\b", r"\bai\s+assistant\b", r"\bvirtual\s+assistant\b",
    r"\ba\.?i\.?\b", r"\bartificial\s+intelligence\b", r"\brobot\b",
    r"\bcomputer\b", r"\bautomated\s+system\b",
)
RECORDING_DISCLOSURE_PATTERNS = (
    r"\brecorded\b", r"\brecording\b", r"\bbeing\s+recorded\b",
)

# A verbal do-not-call request. Deliberately broad: someone asking to be left
# alone rarely phrases it the way a keyword list expects.
VERBAL_OPT_OUT_PATTERNS = (
    r"\btake me off\b", r"\bremove me\b", r"\bdo not call\b", r"\bdon'?t call\b",
    r"\bstop calling\b", r"\bnot interested\b.*\bagain\b", r"\bnever call\b",
    r"\bopt me out\b", r"\bunsubscribe\b", r"\bquit calling\b",
)


def requires_all_party_consent(state: str | None) -> bool:
    """Whether recording needs every party's consent in this state.

    An unknown state returns True. A missing state is missing information, and
    guessing that the permissive rule applies is the one direction that carries
    criminal exposure.
    """
    normalized = (state or "").strip().upper()
    if not normalized:
        return True
    return normalized in ALL_PARTY_CONSENT_STATES


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def discloses_ai(opening_line: str) -> bool:
    return _matches_any(opening_line or "", AI_DISCLOSURE_PATTERNS)


def discloses_recording(opening_line: str) -> bool:
    return _matches_any(opening_line or "", RECORDING_DISCLOSURE_PATTERNS)


def detect_verbal_opt_out(transcript: str) -> bool:
    return _matches_any(transcript or "", VERBAL_OPT_OUT_PATTERNS)


def validate_call_script(
    opening_line: str,
    state: str | None,
    record: bool,
) -> list[str]:
    """Why this call may not be placed, or an empty list."""
    problems: list[str] = []
    text = (opening_line or "").strip()
    if not text:
        return ["missing_opening_line"]

    if not discloses_ai(text):
        problems.append("opening_line_does_not_disclose_automated_system")

    if record:
        if not discloses_recording(text):
            problems.append("opening_line_does_not_disclose_recording")
        if requires_all_party_consent(state) and not discloses_recording(text):
            problems.append(f"all_party_consent_state_requires_recording_disclosure:{state or 'unknown'}")

    if not (os.getenv("BLAND_AI_API_KEY") or "").strip():
        problems.append("bland_api_key_not_configured")
    return problems


@router.post("/preflight")
def preflight(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
):
    """Check a call script before anyone requests approval for it."""
    state = str(payload.get("state") or "").strip().upper() or None
    record = bool(payload.get("record"))
    problems = validate_call_script(str(payload.get("opening_line") or ""), state, record)
    return {
        "organization_id": principal.organization_id,
        "state": state,
        "record": record,
        "all_party_consent_state": requires_all_party_consent(state),
        "placeable": not problems,
        "blockers": problems,
        "note": (
            "Script checks only. The outbound gateway additionally requires a compliance "
            "decision covering written consent, DNC and quiet hours, plus owner approval. "
            "An AI voice is an artificial voice under the FCC's 2024 ruling, so calls to a "
            "mobile number need prior express written consent."
        ),
    }


@router.post("/inbound")
def inbound(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Record an inbound or completed call and honour any spoken opt-out.

    This takes an authenticated principal, so Bland's webhook cannot be pointed
    at it directly -- the payload has to be relayed by something holding a
    workspace token, which is how ``sms_engine`` handles inbound too. It keeps
    the tenant unambiguous and avoids an unauthenticated public write endpoint;
    the cost is a relay step when the provider is wired up.

    A request to stop calling is acted on immediately rather than queued: the
    caller has already said it once, and a queue means the next call may go out
    before anyone reads it.
    """
    contact = normalize_phone(str(payload.get("from") or payload.get("phone_number") or ""))
    if not contact:
        raise HTTPException(422, "from or phone_number is required")

    transcript = str(payload.get("transcript") or payload.get("concatenated_transcript") or "")
    lead_id = payload.get("lead_id")
    lead_id = int(lead_id) if lead_id else None
    state = str(payload.get("state") or "").strip().upper() or None
    opted_out = detect_verbal_opt_out(transcript)

    call = VoiceCall(
        organization_id=principal.organization_id,
        lead_id=lead_id,
        direction=str(payload.get("direction") or "inbound"),
        contact=contact,
        state=state,
        provider="bland",
        provider_call_id=str(payload.get("call_id") or "") or None,
        status="completed",
        outcome=str(payload.get("outcome") or payload.get("status") or "") or None,
        duration_seconds=float(payload["duration"]) if payload.get("duration") else None,
        ai_disclosed=bool(payload.get("ai_disclosed")),
        recorded=bool(payload.get("recorded")),
        recording_consent_basis=str(payload.get("recording_consent_basis") or "") or None,
        verbal_opt_out=opted_out,
        transcript_excerpt=transcript[:2000] or None,
        evidence={"provider_payload_keys": sorted(payload)},
    )
    db.add(call)

    action = "logged"
    if opted_out:
        # Both call channels and SMS. Someone asking not to be called has not
        # invited a text instead, and the request is about being contacted.
        for channel in ("live_call", "automated_call"):
            _suppress_channel(db, principal.organization_id, contact, channel, lead_id)
        # SMS goes through sms_engine.suppress, which also revokes any standing
        # SMS consent record rather than leaving one for a later process to read.
        suppress(
            db, principal.organization_id, contact,
            reason="verbal_do_not_call_request",
            source="inbound_call_transcript",
            lead_id=lead_id,
        )
        action = "suppressed_all_channels"

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        activity_type="voice_call_inbound",
        summary=f"Call with {contact}: {action}",
        metadata_json={"contact": contact, "verbal_opt_out": opted_out, "action": action},
    ))
    db.commit()
    return {
        "contact": contact,
        "verbal_opt_out": opted_out,
        "action": action,
        "call_id": call.id,
    }


def _suppress_channel(
    db: Session, organization_id: int, contact: str, channel: str, lead_id: int | None
) -> None:
    """Suppress one non-SMS channel.

    ``sms_engine.suppress`` also revokes SMS consent records, which is right
    for messaging and wrong here, so the call channels get a plain suppression.
    """
    from .compliance_models import ContactSuppression

    existing = db.scalar(select(ContactSuppression).where(
        ContactSuppression.organization_id == organization_id,
        ContactSuppression.channel == channel,
        ContactSuppression.contact == contact,
    ))
    if existing:
        existing.active = True
        existing.reason = "verbal_do_not_call_request"
        existing.source = "inbound_call_transcript"
        return
    db.add(ContactSuppression(
        organization_id=organization_id, lead_id=lead_id, channel=channel,
        contact=contact, reason="verbal_do_not_call_request",
        source="inbound_call_transcript", active=True,
    ))


@router.get("/recording-rules/{state}")
def recording_rules(state: str, principal: Principal = Depends(get_principal)):
    normalized = state.strip().upper()
    all_party = requires_all_party_consent(normalized)
    return {
        "organization_id": principal.organization_id,
        "state": normalized or None,
        "all_party_consent_required": all_party,
        "guidance": (
            "Every party must consent before recording. The opening line must announce it."
            if all_party else
            "One-party consent is the general rule here, but announcing the recording is still "
            "the safer practice and is required if any participant may be in another state."
        ),
        "advisory": (
            "Routing guidance, not legal advice. Sources disagree on several states, so the "
            "contested ones are treated as all-party. Interstate calls can attract the stricter "
            "state's rule. Confirm with counsel before recording anything."
        ),
    }

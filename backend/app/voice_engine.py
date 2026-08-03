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

import base64
import hashlib
import hmac
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity
from .compliance import normalize_phone
from .database import get_db
from .outbound_models import OutboundRequest
from .sms_engine import suppress
from .voice_models import VoiceCall

logger = logging.getLogger(__name__)

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


def inbound_number() -> str | None:
    """The number sellers call in on, in E.164, or None if unset.

    Distinct from the outbound caller ID. ``BLAND_DEFAULT_CALLER_ID`` is an
    outbound name -- the caller ID a call is placed *from* -- so the inbound
    line needs its own variable rather than borrowing that one. Putting the
    inbound number there would make it the fallback outbound caller ID, and a
    typo in the real one would silently start dialling from the inbound line.
    """
    raw = str(os.getenv("BLAND_INBOUND_NUMBER") or "").strip()
    if not raw:
        return None
    if not re.match(r"^\+[1-9]\d{7,14}$", raw):
        raise HTTPException(503, (
            f"BLAND_INBOUND_NUMBER is not a valid E.164 number: {raw!r}. "
            "Expected +15551234567 with no quotes, spaces or dashes."
        ))
    return raw


def callback_reachability() -> dict[str, Any]:
    """Whether someone returning a missed call reaches the inbound agent.

    This is not only an operational question. Under 47 CFR 64.1601(e) a
    telemarketing call must transmit a caller ID number the called party can
    dial back to make a do-not-call request. A caller ID that rings nowhere
    does not satisfy that, and it also loses every seller who calls back
    instead of answering -- which, on cold outbound, is a lot of them.

    Reported rather than enforced: the caller ID may be forwarded to the
    inbound line by the carrier, which cannot be determined from here.
    """
    from .outbound_gateway import caller_id

    outbound, inbound = caller_id(), inbound_number()
    if not outbound or not inbound:
        return {
            "outbound_caller_id": outbound,
            "inbound_number": inbound,
            "callback_reaches_inbound_agent": None,
            "note": "Configure both numbers to check whether callbacks are answered.",
        }
    same = outbound == inbound
    return {
        "outbound_caller_id": outbound,
        "inbound_number": inbound,
        "callback_reaches_inbound_agent": same,
        "note": (
            "Callbacks to the caller ID reach the inbound agent."
            if same else
            f"Calls display {outbound} but the inbound agent answers {inbound}. "
            "Anyone returning the call reaches the caller ID, not the agent, unless "
            "the carrier forwards it. 47 CFR 64.1601(e) requires a telemarketing "
            "caller ID that can be dialled back to make a do-not-call request, so "
            "either place calls from the inbound number or forward the caller ID to it."
        ),
    }


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
    reachability = callback_reachability()
    warnings: list[str] = []
    if reachability["callback_reaches_inbound_agent"] is False:
        warnings.append("caller_id_does_not_reach_the_inbound_agent")
    elif reachability["callback_reaches_inbound_agent"] is None:
        warnings.append("callback_reachability_unknown")
    return {
        "organization_id": principal.organization_id,
        "state": state,
        "record": record,
        "all_party_consent_state": requires_all_party_consent(state),
        "placeable": not problems,
        "blockers": problems,
        # Warnings, not blockers: the caller ID may be forwarded to the inbound
        # line by the carrier, which cannot be determined from here.
        "warnings": warnings,
        "callback": reachability,
        "note": (
            "Script checks only. The outbound gateway additionally requires a compliance "
            "decision covering written consent, DNC and quiet hours, plus owner approval. "
            "An AI voice is an artificial voice under the FCC's 2024 ruling, so calls to a "
            "mobile number need prior express written consent."
        ),
    }


def record_call(
    db: Session,
    organization_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    """Log a completed call and honour any spoken opt-out.

    Shared by the authenticated route and the signed webhook so the two cannot
    drift. A drifting copy here would mean an opt-out honoured on one path and
    silently dropped on the other, which is the failure that costs the most.

    A request to stop calling is acted on immediately rather than queued: the
    caller has already said it once, and a queue means the next call may go out
    before anyone reads it.
    """
    contact = normalize_phone(str(payload.get("from") or payload.get("phone_number") or ""))
    if not contact:
        raise HTTPException(422, "from or phone_number is required")

    provider_call_id = str(payload.get("call_id") or "") or None
    if provider_call_id:
        # Providers retry. Without this, one redelivery becomes a second call
        # record and a duplicated activity entry.
        existing = db.scalar(select(VoiceCall).where(
            VoiceCall.organization_id == organization_id,
            VoiceCall.provider_call_id == provider_call_id,
            VoiceCall.direction != "outbound",
        ))
        if existing:
            return {
                "contact": existing.contact,
                "verbal_opt_out": existing.verbal_opt_out,
                "action": "already_recorded",
                "call_id": existing.id,
                "duplicate": True,
            }

    transcript = str(payload.get("transcript") or payload.get("concatenated_transcript") or "")
    lead_id = payload.get("lead_id")
    lead_id = int(lead_id) if lead_id else None
    state = str(payload.get("state") or "").strip().upper() or None
    opted_out = detect_verbal_opt_out(transcript)

    call = VoiceCall(
        organization_id=organization_id,
        lead_id=lead_id,
        direction=str(payload.get("direction") or "inbound"),
        contact=contact,
        state=state,
        provider="bland",
        provider_call_id=provider_call_id,
        status="completed",
        outcome=str(payload.get("outcome") or payload.get("status") or "") or None,
        duration_seconds=float(payload["duration"]) if payload.get("duration") else None,
        ai_disclosed=bool(payload.get("ai_disclosed")),
        recorded=bool(payload.get("recorded")),
        recording_consent_basis=str(payload.get("recording_consent_basis") or "") or None,
        verbal_opt_out=opted_out,
        transcript_excerpt=transcript[:2000] or None,
        evidence={
            "provider_payload_keys": sorted(payload),
            "source": source,
            # Which of our numbers was dialled. Worth keeping: it is the only
            # way to tell later which line a call actually arrived on.
            "to": normalize_phone(str(payload.get("to") or "")) or None,
        },
    )
    db.add(call)

    action = "logged"
    if opted_out:
        # Both call channels and SMS. Someone asking not to be called has not
        # invited a text instead, and the request is about being contacted.
        for channel in ("live_call", "automated_call"):
            _suppress_channel(db, organization_id, contact, channel, lead_id)
        # SMS goes through sms_engine.suppress, which also revokes any standing
        # SMS consent record rather than leaving one for a later process to read.
        suppress(
            db, organization_id, contact,
            reason="verbal_do_not_call_request",
            source="inbound_call_transcript",
            lead_id=lead_id,
        )
        action = "suppressed_all_channels"

    db.add(CrmActivity(
        organization_id=organization_id,
        user_id=user_id,
        lead_id=lead_id,
        activity_type="voice_call_inbound",
        summary=f"Call with {contact}: {action}",
        metadata_json={
            "contact": contact, "verbal_opt_out": opted_out,
            "action": action, "source": source,
        },
    ))
    db.commit()
    return {
        "contact": contact,
        "verbal_opt_out": opted_out,
        "action": action,
        "call_id": call.id,
        "duplicate": False,
    }


@router.post("/inbound")
def inbound(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Record a call on behalf of an authenticated caller.

    Kept alongside the signed webhook for relaying a payload by hand -- a
    replay of a delivery Bland has already sent, or a call logged from another
    system. The webhook is what Bland itself should point at.
    """
    return record_call(db, principal.organization_id, principal.user_id, payload, source="authenticated")


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


# ---------------------------------------------------------------- webhook --
#
# Bland's published header name could not be confirmed while this was written,
# so verification tries the conventional names rather than hardcoding a guess.
# BLAND_AI_WEBHOOK_SIGNATURE_HEADER pins it once you know which one arrives,
# and a rejected delivery reports the header names it did carry, so the first
# real delivery tells you the answer instead of failing silently.
SIGNATURE_HEADER_CANDIDATES = (
    "x-webhook-signature", "x-bland-signature", "x-signature", "signature",
)


def _webhook_secret() -> str:
    return str(os.getenv("BLAND_AI_WEBHOOK_SECRET") or "").strip()


def _signature_headers() -> tuple[str, ...]:
    configured = str(os.getenv("BLAND_AI_WEBHOOK_SIGNATURE_HEADER") or "").strip().lower()
    return (configured,) if configured else SIGNATURE_HEADER_CANDIDATES


def _expected_signatures(secret: str, body: bytes) -> set[str]:
    """Every encoding a sane provider might use for the same HMAC.

    Accepting hex and base64 of the same digest is not a weakening: both are
    derived from the secret, so neither can be produced without it.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return {digest.hexdigest(), base64.b64encode(digest.digest()).decode("ascii")}


def _presented_signature(headers: Any) -> tuple[str | None, str | None]:
    for name in _signature_headers():
        raw = headers.get(name)
        if raw:
            value = str(raw).strip()
            # "sha256=<hex>" is a common wrapping; compare the payload only.
            if "=" in value and value.split("=", 1)[0].lower() in {"sha256", "sha-256", "v1"}:
                value = value.split("=", 1)[1].strip()
            return name, value
    return None, None


def verify_webhook_signature(headers: Any, body: bytes) -> tuple[bool, str]:
    """Whether this delivery was signed with the shared secret.

    Fails closed on a missing secret. An unauthenticated public write endpoint
    that accepts anything when misconfigured is worse than one that is down,
    because nothing about it looks broken.
    """
    secret = _webhook_secret()
    if not secret:
        return False, "webhook_secret_not_configured"

    name, presented = _presented_signature(headers)
    if not presented:
        return False, "no_signature_header"

    for expected in _expected_signatures(secret, body):
        # compare_digest, not ==, so a wrong signature cannot be recovered one
        # character at a time from how long the comparison took.
        if hmac.compare_digest(presented, expected):
            return True, name
    return False, "signature_mismatch"


def _resolve_organization(db: Session, payload: dict[str, Any]) -> int | None:
    """Which workspace this call belongs to.

    Only reached once the signature has verified, so the payload is known to
    come from Bland. The call id is preferred over the echoed metadata anyway:
    it is matched against a record this system wrote, which does not depend on
    the provider round-tripping anything faithfully.
    """
    call_id = str(payload.get("call_id") or "").strip()
    if call_id:
        prior = db.scalar(select(VoiceCall).where(VoiceCall.provider_call_id == call_id))
        if prior:
            return prior.organization_id
        request = db.scalar(select(OutboundRequest).where(OutboundRequest.provider_reference == call_id))
        if request:
            return request.organization_id

    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and str(metadata.get("organization_id") or "").isdigit():
        return int(metadata["organization_id"])

    # Inbound calls have no prior record: nobody here started them. A single
    # configured workspace is the fallback, and without it the delivery is
    # rejected rather than filed against a guess.
    configured = str(os.getenv("BLAND_INBOUND_ORGANIZATION_ID") or "").strip()
    return int(configured) if configured.isdigit() else None


@router.post("/webhooks/bland")
async def bland_webhook(request: Request, db: Session = Depends(get_db)):
    """Bland posts call results here.

    The signature is computed over the exact bytes received, so the body is
    read raw and parsed only after verification. Parsing first and re-encoding
    would change the bytes -- key order and whitespace both -- and the
    signature would never match.
    """
    body = await request.body()
    verified, detail = verify_webhook_signature(request.headers, body)
    if not verified:
        # The header names are echoed back because the one thing this cannot
        # tell you from here is which name Bland actually uses. Names only:
        # the values are the caller's own, but there is no reason to repeat
        # them. Bland surfaces the response body in its delivery log.
        raise HTTPException(401, {
            "error": detail,
            "looked_for": list(_signature_headers()),
            "received_headers": sorted(request.headers.keys()),
            "hint": (
                "Set BLAND_AI_WEBHOOK_SECRET to the signing secret, and "
                "BLAND_AI_WEBHOOK_SIGNATURE_HEADER if the header carrying the "
                "signature is not one of the names looked for."
            ),
        })

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(422, "Webhook body is not valid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(422, "Webhook body must be a JSON object")

    organization_id = _resolve_organization(db, payload)
    if organization_id is None:
        # Signed but unattributable. Recording it against a guessed workspace
        # would put one tenant's call in another's ledger, so it is refused
        # loudly; a 4xx keeps the delivery visible in Bland's retry log rather
        # than disappearing into a success response.
        logger.warning("bland webhook verified but not attributable to a workspace")
        raise HTTPException(422, {
            "error": "call_not_attributable_to_a_workspace",
            "hint": (
                "Outbound calls resolve from the call id. Inbound calls need "
                "BLAND_INBOUND_ORGANIZATION_ID set to the workspace that owns "
                "the receiving number."
            ),
        })

    result = record_call(db, organization_id, None, payload, source=f"bland_webhook:{detail}")
    return {"accepted": True, **result}


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

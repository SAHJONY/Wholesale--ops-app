"""SMS that can prove it was allowed to send.

Texting a homeowner is the highest-liability action this system takes. TCPA
damages are statutory and per message, so the interesting engineering is not
delivery -- any provider does that -- but establishing, for each individual
message, that sending it was permitted, and being able to show why afterwards.

The compliance evaluation in ``compliance.py`` already covers suppression,
consent, DNC and quiet hours. This adds the parts specific to messaging:

**Opt-out is honoured on arrival.** STOP and its variants revoke consent and
suppress the number permanently, before any reply is generated and without
waiting for a human. Where a message is ambiguous the tie goes to suppression:
wrongly suppressing costs a lead, wrongly sending costs a statutory penalty per
message, and those errors are not the same size.

**Frequency is capped from the send log.** Volume is what turns a lawful
campaign into a harassment claim and what gets a sender filtered by carriers,
so the cap is counted from messages actually recorded rather than intended.

**Content is gated, whoever wrote it.** Every outbound body must identify the
sender and carry opt-out instructions. The drafter below produces text that
satisfies this by construction, but the gate runs on the final body regardless
of origin, so a hand-written or model-written message cannot skip it. The gate
is authoritative; the drafter is a convenience.

Nothing here sends. Delivery stays with the controlled outbound gateway, which
requires a fresh compliance decision and owner approval.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .compliance import normalize_phone
from .compliance_models import ContactConsent, ContactSuppression
from .database import get_db
from .models import Lead
from .sms_models import SmsMessage

router = APIRouter(prefix="/sms", tags=["compliant sms"])

# Carrier-recognised opt-out keywords. STOP is mandatory; the rest are the
# conventional set subscribers actually use.
OPT_OUT_KEYWORDS = frozenset({
    "stop", "stopall", "unsubscribe", "cancel", "end", "quit", "optout", "opt-out", "revoke",
})
HELP_KEYWORDS = frozenset({"help", "info"})
OPT_IN_KEYWORDS = frozenset({"start", "unstop", "yes"})

# Rolling frequency limit per recipient.
MAX_MESSAGES_PER_WINDOW = 3
FREQUENCY_WINDOW_DAYS = 7

# A body must carry both to be sendable.
OPT_OUT_INSTRUCTION_PATTERN = re.compile(r"\b(reply\s+)?stop\b", re.I)
SEGMENT_LIMIT = 320  # two segments; longer bodies fragment and cost more.


def business_name() -> str:
    return (os.getenv("SMS_BUSINESS_NAME") or "").strip()


def classify_inbound(body: str) -> tuple[str | None, str]:
    """Recognise a keyword in an inbound message.

    Matching is deliberately generous at the front of the message. A subscriber
    replying "STOP." or "stop please" means to opt out, and refusing to see that
    because of punctuation or a trailing word is the expensive mistake. A
    keyword appearing mid-sentence is not treated as a command, so "don't stop
    sending" is not read as consent to keep going either -- it simply is not a
    keyword message, and a human reads it.
    """
    normalized = re.sub(r"[^a-z0-9\s-]", " ", (body or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return None, ""
    first = normalized.split(" ", 1)[0]
    for keywords, kind in (
        (OPT_OUT_KEYWORDS, "opt_out"),
        (HELP_KEYWORDS, "help"),
        (OPT_IN_KEYWORDS, "opt_in"),
    ):
        if normalized in keywords or first in keywords:
            return kind, first
    return None, ""


def validate_body(body: str) -> list[str]:
    """Why this body may not be sent, or an empty list."""
    problems: list[str] = []
    text = (body or "").strip()
    if not text:
        return ["empty_body"]

    name = business_name()
    if not name:
        problems.append("sms_business_name_not_configured")
    elif name.lower() not in text.lower():
        # 10DLC and CTIA both require the message to say who is texting.
        problems.append("missing_sender_identification")

    if not OPT_OUT_INSTRUCTION_PATTERN.search(text):
        problems.append("missing_opt_out_instruction")

    if len(text) > SEGMENT_LIMIT:
        problems.append("body_exceeds_two_segments")
    return problems


def recent_message_count(db: Session, organization_id: int, contact: str, now: datetime) -> int:
    since = now - timedelta(days=FREQUENCY_WINDOW_DAYS)
    return int(db.scalar(select(func.count(SmsMessage.id)).where(
        SmsMessage.organization_id == organization_id,
        SmsMessage.contact == contact,
        SmsMessage.direction == "outbound",
        SmsMessage.created_at >= since,
    )) or 0)


def suppress(
    db: Session,
    organization_id: int,
    contact: str,
    reason: str,
    source: str,
    lead_id: int | None = None,
) -> ContactSuppression:
    """Suppress a number and revoke its consent.

    Both, deliberately. A suppression that leaves consent standing invites a
    later process to read the consent record and conclude it may send.
    """
    existing = db.scalar(select(ContactSuppression).where(
        ContactSuppression.organization_id == organization_id,
        ContactSuppression.channel == "sms",
        ContactSuppression.contact == contact,
    ))
    if existing:
        existing.active = True
        existing.reason = reason
        existing.source = source
        suppression = existing
    else:
        suppression = ContactSuppression(
            organization_id=organization_id, lead_id=lead_id, channel="sms",
            contact=contact, reason=reason, source=source, active=True,
        )
        db.add(suppression)

    now = datetime.now(timezone.utc)
    for consent in db.scalars(select(ContactConsent).where(
        ContactConsent.organization_id == organization_id,
        ContactConsent.channel == "sms",
        ContactConsent.contact == contact,
        ContactConsent.revoked_at.is_(None),
    )).all():
        consent.revoked_at = now
        consent.status = "revoked"
    return suppression


@router.post("/inbound")
def inbound(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Record an inbound message and act on any keyword immediately.

    Opt-out takes effect here, on receipt. Queueing it for review would leave a
    window in which the system could lawfully be told to stop and still send.
    """
    contact = normalize_phone(str(payload.get("from") or ""))
    body = str(payload.get("body") or "")
    if not contact:
        raise HTTPException(422, "from is required")

    kind, keyword = classify_inbound(body)
    lead_id = payload.get("lead_id")
    lead_id = int(lead_id) if lead_id else None

    message = SmsMessage(
        organization_id=principal.organization_id,
        lead_id=lead_id,
        direction="inbound",
        contact=contact,
        body=body,
        keyword=keyword or None,
        triggered_opt_out=kind == "opt_out",
        status="received",
        evidence={"classified_as": kind},
    )
    db.add(message)

    action = "logged_for_human_review"
    if kind == "opt_out":
        suppress(db, principal.organization_id, contact, "recipient_opt_out", f"inbound_sms:{keyword}", lead_id)
        action = "suppressed_and_consent_revoked"
    elif kind == "opt_in":
        # Never an automatic resubscribe. Opting back in has to re-establish
        # consent through the same evidence path as the first time, or STOP
        # would be undoable by a stray word.
        action = "opt_in_keyword_noted_consent_not_restored"

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        activity_type=f"sms_inbound_{kind or 'message'}",
        summary=f"Inbound SMS from {contact}: {action}",
        metadata_json={"contact": contact, "keyword": keyword, "action": action},
    ))
    db.commit()
    return {
        "contact": contact,
        "classified_as": kind,
        "keyword": keyword or None,
        "action": action,
        "reply_required": kind in {"opt_out", "help"},
    }


@router.post("/preflight")
def preflight(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Report whether a specific body may go to a specific number, and why not.

    Runs the messaging-specific checks. It does not replace the compliance
    evaluation the outbound gateway requires; both must pass, and this one
    exists so a campaign can be corrected before anyone requests approval.
    """
    contact = normalize_phone(str(payload.get("contact") or ""))
    body = str(payload.get("body") or "")
    if not contact:
        raise HTTPException(422, "contact is required")

    now = datetime.now(timezone.utc)
    blockers = validate_body(body)

    suppression = db.scalar(select(ContactSuppression).where(
        ContactSuppression.organization_id == principal.organization_id,
        ContactSuppression.channel == "sms",
        ContactSuppression.contact == contact,
        ContactSuppression.active.is_(True),
    ))
    if suppression:
        blockers.append("contact_suppressed")

    sent = recent_message_count(db, principal.organization_id, contact, now)
    if sent >= MAX_MESSAGES_PER_WINDOW:
        blockers.append("frequency_cap_reached")

    return {
        "organization_id": principal.organization_id,
        "contact": contact,
        "sendable": not blockers,
        "blockers": blockers,
        "messages_in_window": sent,
        "frequency_cap": MAX_MESSAGES_PER_WINDOW,
        "window_days": FREQUENCY_WINDOW_DAYS,
        "note": (
            "Messaging checks only. The outbound gateway additionally requires a fresh "
            "compliance decision covering consent, DNC and quiet hours, plus owner approval."
        ),
    }


# ------------------------------------------------------------------ drafting --

# One opener per distress trigger, because the same words do not work across
# them. Each is written to be low-pressure and to state the reason for contact,
# which is both better practice and what a regulator reads first.
#
# Probate and foreclosure are handled with particular care. Neither mentions the
# filing itself: telling someone you know their relative died or that their home
# is in foreclosure reads as surveillance, and several states regulate
# foreclosure-related solicitation specifically. The opener says only that the
# sender buys property in the area.
TEMPLATES: dict[str, str] = {
    "tax_delinquency": (
        "Hi {first_name}, this is {agent} with {business}. "
        "I buy homes in {city} and wondered if you'd consider an offer on {street}. "
        "No repairs or fees on your side. Reply STOP to opt out."
    ),
    "code_violation": (
        "Hi {first_name}, {agent} here with {business}. "
        "We buy houses in {city} as-is, including ones needing work. "
        "Would you be open to a cash offer on {street}? Reply STOP to opt out."
    ),
    "probate": (
        "Hello {first_name}, this is {agent} with {business}. "
        "We buy homes in {city} and can work on your timeline with no repairs needed. "
        "Is {street} something you'd consider selling? Reply STOP to opt out."
    ),
    "lis_pendens": (
        "Hi {first_name}, {agent} with {business}. "
        "I buy houses in {city} and can close quickly if that's useful to you. "
        "Would you like an offer on {street}? Reply STOP to opt out."
    ),
    "vacant": (
        "Hi {first_name}, this is {agent} with {business}. "
        "I noticed {street} may be vacant and I buy homes in {city} as-is. "
        "Open to an offer? Reply STOP to opt out."
    ),
    "general": (
        "Hi {first_name}, this is {agent} with {business}. "
        "I buy homes in {city} and would like to make an offer on {street} if you're open to it. "
        "Reply STOP to opt out."
    ),
}


def draft_message(
    trigger: str,
    first_name: str,
    street: str,
    city: str,
    agent: str,
) -> dict[str, Any]:
    """Compose a message for a distress trigger and check it like any other.

    The template already carries the sender's name and the opt-out instruction,
    so a draft should pass. It is validated anyway: the gate has to be the thing
    that decides, or a future template edit becomes a silent compliance change.
    """
    template = TEMPLATES.get(trigger, TEMPLATES["general"])
    body = template.format(
        first_name=(first_name or "there").split(" ")[0],
        street=street or "your property",
        city=city or "the area",
        agent=agent or "our team",
        business=business_name() or "BUSINESS_NAME_NOT_SET",
    )
    problems = validate_body(body)
    return {
        "trigger": trigger if trigger in TEMPLATES else "general",
        "body": body,
        "characters": len(body),
        "segments": 1 if len(body) <= 160 else 2,
        "sendable": not problems,
        "blockers": problems,
    }


@router.post("/draft")
def draft(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Draft a message for a lead. Composes text; sends nothing."""
    lead_id = int(payload.get("lead_id") or 0)
    lead = db.get(Lead, lead_id) if lead_id else None
    if not lead:
        raise HTTPException(404, "Lead not found")

    prop = lead.property
    result = draft_message(
        trigger=str(payload.get("trigger") or "general"),
        first_name=lead.seller_name or "",
        street=(prop.address if prop else "") or "",
        city=(prop.city if prop else "") or "",
        agent=str(payload.get("agent_name") or ""),
    )
    return {"organization_id": principal.organization_id, "lead_id": lead.id, **result}


@router.get("/templates")
def templates(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "business_name_configured": bool(business_name()),
        "triggers": sorted(TEMPLATES),
        "requirements": [
            "Every body must name the sender and carry opt-out instructions.",
            "Probate and foreclosure openers never reference the filing itself.",
            f"At most {MAX_MESSAGES_PER_WINDOW} messages per number per {FREQUENCY_WINDOW_DAYS} days.",
            "Quiet hours are enforced in the recipient's local time, not the sender's.",
        ],
    }

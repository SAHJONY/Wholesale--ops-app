from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .compliance import evaluate_contact
from .database import get_db
from .models import Approval, Lead
from .outbound_gateway import create_outbound_request
from .sms_campaign_models import SmsCampaign, SmsCampaignRecipient, SmsMessageTemplate

router = APIRouter(prefix="/sms-campaign-execution", tags=["SAHJONY SMS campaign execution"])

MAX_APPROVAL_BATCH = 25
SINGLE_ZONE_STATE_TIMEZONES = {
    "AL": "America/Chicago", "AZ": "America/Phoenix", "AR": "America/Chicago",
    "CA": "America/Los_Angeles", "CO": "America/Denver", "CT": "America/New_York",
    "DC": "America/New_York", "DE": "America/New_York", "GA": "America/New_York",
    "HI": "Pacific/Honolulu", "IA": "America/Chicago", "IL": "America/Chicago",
    "LA": "America/Chicago", "MA": "America/New_York", "MD": "America/New_York",
    "ME": "America/New_York", "MN": "America/Chicago", "MO": "America/Chicago",
    "MS": "America/Chicago", "MT": "America/Denver", "NC": "America/New_York",
    "NH": "America/New_York", "NJ": "America/New_York", "NM": "America/Denver",
    "NV": "America/Los_Angeles", "NY": "America/New_York", "OH": "America/New_York",
    "OK": "America/Chicago", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "UT": "America/Denver", "VA": "America/New_York",
    "VT": "America/New_York", "WA": "America/Los_Angeles", "WI": "America/Chicago",
    "WV": "America/New_York", "WY": "America/Denver",
}
MULTI_ZONE_STATES = frozenset({"AK", "FL", "ID", "IN", "KS", "KY", "MI", "NE", "ND", "OR", "SD", "TN", "TX"})


def _campaign(db: Session, principal: Principal, campaign_id: int) -> SmsCampaign:
    campaign = db.get(SmsCampaign, campaign_id)
    if not campaign or campaign.organization_id != principal.organization_id:
        raise HTTPException(404, "Campaign not found")
    return campaign


def _template(db: Session, principal: Principal, template_id: int | None) -> SmsMessageTemplate:
    if not template_id:
        raise HTTPException(422, "Campaign has no message template")
    template = db.get(SmsMessageTemplate, template_id)
    if not template or template.organization_id != principal.organization_id:
        raise HTTPException(404, "Message template not found")
    return template


def infer_recipient_timezone(lead: Lead, explicit: str | None = None) -> tuple[str | None, str]:
    if explicit and explicit.strip():
        return explicit.strip(), "explicit_override"
    state = str(getattr(getattr(lead, "property", None), "state", "") or "").upper().strip()
    if not state:
        return None, "property_state_missing"
    if state in MULTI_ZONE_STATES:
        return None, "multi_zone_state_requires_exact_timezone"
    zone = SINGLE_ZONE_STATE_TIMEZONES.get(state)
    return (zone, "single_zone_state_inference") if zone else (None, "timezone_not_mapped")


def _override(payload: dict, recipient: SmsCampaignRecipient) -> str | None:
    overrides = payload.get("timezone_overrides")
    if not isinstance(overrides, dict):
        return None
    for key in (str(recipient.lead_id), str(recipient.contact)):
        value = overrides.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


@router.get("/{campaign_id}/readiness")
def readiness(campaign_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    campaign = _campaign(db, principal, campaign_id)
    rows = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
    )).all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "campaign_id": campaign.id,
        "campaign_status": campaign.status,
        "recipient_statuses": counts,
        "can_build_approvals": counts.get("needs_compliance", 0) + counts.get("needs_timezone", 0) > 0,
        "can_owner_approve": counts.get("pending_owner_approval", 0) > 0,
        "max_approval_batch": MAX_APPROVAL_BATCH,
        "dispatch_is_separate": True,
    }


@router.post("/{campaign_id}/build-approvals")
def build_approvals(
    campaign_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Create recipient-specific compliance decisions and owner approvals.

    No SMS is sent. Single-zone states may be inferred. Multi-zone states fail
    closed unless an exact recipient timezone override is supplied.
    """
    campaign = _campaign(db, principal, campaign_id)
    template = _template(db, principal, campaign.template_id)
    limit = max(1, min(int(payload.get("limit") or 10), MAX_APPROVAL_BATCH))

    recipients = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status.in_(["needs_compliance", "needs_timezone"]),
    ).order_by(SmsCampaignRecipient.id.asc()).limit(limit)).all()

    allowed = blocked = missing_lead = needs_timezone = 0
    created_requests: list[dict] = []
    for recipient in recipients:
        lead = db.get(Lead, recipient.lead_id)
        if not lead or not lead.property:
            recipient.status = "blocked_missing_lead"
            recipient.suppression_reason = "lead_or_property_not_found"
            missing_lead += 1
            continue

        recipient_timezone, timezone_source = infer_recipient_timezone(lead, _override(payload, recipient))
        if not recipient_timezone:
            recipient.status = "needs_timezone"
            recipient.evidence = {
                **(recipient.evidence or {}),
                "timezone_source": timezone_source,
                "timezone_required": True,
            }
            needs_timezone += 1
            continue

        decision = evaluate_contact(db, principal, lead, "sms", recipient.contact, recipient_timezone)
        if not decision["allowed"]:
            recipient.status = "blocked_compliance"
            recipient.suppression_reason = ",".join(decision.get("reasons") or []) or "compliance_blocked"
            recipient.evidence = {
                **(recipient.evidence or {}),
                "recipient_timezone": recipient_timezone,
                "timezone_source": timezone_source,
                "compliance_decision_id": decision["decision_id"],
                "compliance_reasons": decision.get("reasons") or [],
            }
            blocked += 1
            db.commit()
            continue

        content = {
            "body": recipient.rendered_body,
            "new_conversation": True,
            "pathway_id": template.pathway_id,
            "persona_id": template.persona_id,
            "metadata": {
                "campaign_id": campaign.id,
                "campaign_recipient_id": recipient.id,
                "brand": "SAHJONY AI Acquisition",
            },
            "request_data": {
                "campaign_id": campaign.id,
                "campaign_recipient_id": recipient.id,
            },
        }
        result = create_outbound_request({
            "lead_id": lead.id,
            "channel": "sms",
            "provider": "bland",
            "contact": recipient.contact,
            "compliance_decision_id": decision["decision_id"],
            "content": content,
        }, principal, db)
        recipient.status = "pending_owner_approval"
        recipient.outbound_request_id = result["request_id"]
        recipient.evidence = {
            **(recipient.evidence or {}),
            "compliance_decision_id": decision["decision_id"],
            "compliance_expires_at": decision.get("expires_at"),
            "approval_id": result["approval_id"],
            "recipient_timezone": recipient_timezone,
            "timezone_source": timezone_source,
            "approval_built_at": datetime.now(timezone.utc).isoformat(),
        }
        db.commit()
        allowed += 1
        created_requests.append({
            "recipient_id": recipient.id,
            "lead_id": lead.id,
            "outbound_request_id": result["request_id"],
            "approval_id": result["approval_id"],
            "recipient_timezone": recipient_timezone,
        })

    remaining = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status.in_(["needs_compliance", "needs_timezone"]),
    )).all()
    campaign.ready_count = len(remaining)
    campaign.status = "approval_queue" if not remaining else "partially_queued"
    campaign.metadata_json = {
        **(campaign.metadata_json or {}),
        "last_approval_batch": {
            "built": allowed,
            "blocked": blocked,
            "missing_lead": missing_lead,
            "needs_timezone": needs_timezone,
            "at": datetime.now(timezone.utc).isoformat(),
        },
    }
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="sms_campaign_approval_batch_built",
        summary=f"Built {allowed} owner approvals for campaign {campaign.name}",
        metadata_json={
            "campaign_id": campaign.id,
            "allowed": allowed,
            "blocked": blocked,
            "missing_lead": missing_lead,
            "needs_timezone": needs_timezone,
            "remaining": len(remaining),
        },
    ))
    db.commit()
    return {
        "campaign_id": campaign.id,
        "evaluated": len(recipients),
        "pending_owner_approval": allowed,
        "blocked_compliance": blocked,
        "missing_lead": missing_lead,
        "needs_timezone": needs_timezone,
        "remaining_needs_processing": len(remaining),
        "created_requests": created_requests,
        "dispatch_allowed": False,
        "messages_sent": 0,
    }


@router.post("/{campaign_id}/owner-approve")
def owner_approve_campaign_batch(
    campaign_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Explicit owner approval for a bounded batch; this never dispatches."""
    campaign = _campaign(db, principal, campaign_id)
    limit = max(1, min(int(payload.get("limit") or 10), MAX_APPROVAL_BATCH))
    note = str(payload.get("note") or "Approved from SAHJONY Campaign Manager").strip()

    recipients = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status == "pending_owner_approval",
        SmsCampaignRecipient.outbound_request_id.is_not(None),
    ).order_by(SmsCampaignRecipient.id.asc()).limit(limit)).all()

    approved = 0
    now = datetime.now(timezone.utc)
    for recipient in recipients:
        approval = db.scalar(select(Approval).where(
            Approval.entity_type == "outbound_request",
            Approval.entity_id == recipient.outbound_request_id,
            Approval.status == "pending",
        ).order_by(Approval.created_at.desc()))
        if not approval:
            recipient.status = "approval_missing"
            continue
        approval.status = "approved"
        approval.decided_by = principal.email
        approval.decision_note = note
        approval.decided_at = now
        recipient.status = "approved_not_dispatched"
        approved += 1

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="sms_campaign_owner_approved",
        summary=f"Owner approved {approved} SMS requests for campaign {campaign.name}",
        metadata_json={"campaign_id": campaign.id, "approved": approved, "note": note},
    ))
    db.commit()
    return {
        "campaign_id": campaign.id,
        "approved": approved,
        "dispatch_allowed": bool(approved),
        "dispatched": 0,
        "next_step": "Dispatch remains a separate explicit owner action through the controlled Bland outbound gateway.",
    }

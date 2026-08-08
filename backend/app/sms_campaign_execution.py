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
        "can_build_approvals": counts.get("needs_compliance", 0) > 0,
        "can_owner_approve": counts.get("pending_owner_approval", 0) > 0,
        "dispatch_is_separate": True,
    }


@router.post("/{campaign_id}/build-approvals")
def build_approvals(
    campaign_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Turn prepared recipients into individually evaluated outbound requests.

    This endpoint deliberately stops at owner approval. It may create compliance
    decisions and outbound requests, but it never sends an SMS.
    """
    campaign = _campaign(db, principal, campaign_id)
    template = _template(db, principal, campaign.template_id)
    recipient_timezone = str(payload.get("recipient_timezone") or "").strip()
    if not recipient_timezone:
        raise HTTPException(422, "recipient_timezone is required for SMS quiet-hours evaluation")
    limit = max(1, min(int(payload.get("limit") or 50), 100))

    recipients = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status == "needs_compliance",
    ).order_by(SmsCampaignRecipient.id.asc()).limit(limit)).all()

    allowed = blocked = missing_lead = 0
    created_requests: list[dict] = []
    for recipient in recipients:
        lead = db.get(Lead, recipient.lead_id)
        if not lead:
            recipient.status = "blocked_missing_lead"
            recipient.suppression_reason = "lead_not_found"
            missing_lead += 1
            continue

        decision = evaluate_contact(
            db, principal, lead, "sms", recipient.contact, recipient_timezone
        )
        if not decision["allowed"]:
            recipient.status = "blocked_compliance"
            recipient.suppression_reason = ",".join(decision.get("reasons") or []) or "compliance_blocked"
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
            "approval_id": result["approval_id"],
            "recipient_timezone": recipient_timezone,
            "approval_built_at": datetime.now(timezone.utc).isoformat(),
        }
        db.commit()
        allowed += 1
        created_requests.append({
            "recipient_id": recipient.id,
            "lead_id": lead.id,
            "outbound_request_id": result["request_id"],
            "approval_id": result["approval_id"],
        })

    remaining = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status == "needs_compliance",
    )).all()
    campaign.ready_count = len(remaining)
    campaign.metadata_json = {
        **(campaign.metadata_json or {}),
        "last_approval_batch": {
            "built": allowed,
            "blocked": blocked,
            "missing_lead": missing_lead,
            "recipient_timezone": recipient_timezone,
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
            "remaining_needs_compliance": len(remaining),
        },
    ))
    db.commit()
    return {
        "campaign_id": campaign.id,
        "evaluated": len(recipients),
        "pending_owner_approval": allowed,
        "blocked_compliance": blocked,
        "missing_lead": missing_lead,
        "remaining_needs_compliance": len(remaining),
        "created_requests": created_requests,
        "dispatch_allowed": False,
    }


@router.post("/{campaign_id}/owner-approve")
def owner_approve_campaign_batch(
    campaign_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Explicit owner action that approves a bounded batch; it does not dispatch."""
    campaign = _campaign(db, principal, campaign_id)
    limit = max(1, min(int(payload.get("limit") or 25), 100))
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
        "dispatch_allowed": True if approved else False,
        "dispatched": 0,
        "next_step": "Dispatch remains a separate explicit owner action through the controlled Bland outbound gateway.",
    }

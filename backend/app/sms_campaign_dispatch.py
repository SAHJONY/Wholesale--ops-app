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
from .outbound_gateway import dispatch_outbound_request
from .outbound_models import OutboundRequest
from .sms_campaign_models import SmsCampaign, SmsCampaignRecipient

router = APIRouter(prefix="/sms-campaign-execution", tags=["SAHJONY SMS campaign dispatch"])

MAX_DISPATCH_BATCH = 25


def _campaign(db: Session, principal: Principal, campaign_id: int) -> SmsCampaign:
    campaign = db.get(SmsCampaign, campaign_id)
    if not campaign or campaign.organization_id != principal.organization_id:
        raise HTTPException(404, "Campaign not found")
    return campaign


def recipient_timezone(recipient: SmsCampaignRecipient) -> str | None:
    evidence = recipient.evidence if isinstance(recipient.evidence, dict) else {}
    value = evidence.get("recipient_timezone")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _approved(db: Session, request_id: int) -> bool:
    row = db.scalar(select(Approval.id).where(
        Approval.entity_type == "outbound_request",
        Approval.entity_id == request_id,
        Approval.status == "approved",
    ))
    return bool(row)


@router.get("/{campaign_id}/dispatch-readiness")
def dispatch_readiness(
    campaign_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    campaign = _campaign(db, principal, campaign_id)
    rows = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
    )).all()
    approved = [row for row in rows if row.status == "approved_not_dispatched"]
    missing_timezone = sum(1 for row in approved if not recipient_timezone(row))
    return {
        "campaign_id": campaign.id,
        "campaign_status": campaign.status,
        "approved_not_dispatched": len(approved),
        "missing_timezone": missing_timezone,
        "max_dispatch_batch": MAX_DISPATCH_BATCH,
        "fresh_compliance_required": True,
        "can_dispatch": bool(approved) and missing_timezone == 0,
    }


@router.post("/{campaign_id}/dispatch-approved")
async def dispatch_approved_batch(
    campaign_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    """Dispatch an owner-approved batch only after fresh recipient compliance.

    Approval never freezes compliance. Immediately before each Bland send this
    endpoint re-runs suppression, DNC, consent, and quiet-hours checks using the
    recipient timezone captured during approval construction. A newly blocked
    recipient is never handed to the provider.
    """
    campaign = _campaign(db, principal, campaign_id)
    limit = max(1, min(int(payload.get("limit") or 10), MAX_DISPATCH_BATCH))

    recipients = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status == "approved_not_dispatched",
        SmsCampaignRecipient.outbound_request_id.is_not(None),
    ).order_by(SmsCampaignRecipient.id.asc()).limit(limit)).all()

    sent = blocked = failed = missing = 0
    results: list[dict] = []
    for recipient in recipients:
        request = db.get(OutboundRequest, recipient.outbound_request_id)
        lead = db.get(Lead, recipient.lead_id)
        timezone_name = recipient_timezone(recipient)
        if not request or request.organization_id != principal.organization_id or not lead:
            recipient.status = "dispatch_blocked_missing_record"
            recipient.suppression_reason = "outbound_request_or_lead_missing"
            missing += 1
            db.commit()
            continue
        if not timezone_name:
            recipient.status = "needs_timezone"
            recipient.suppression_reason = "recipient_timezone_missing_at_dispatch"
            missing += 1
            db.commit()
            continue
        if not _approved(db, request.id):
            recipient.status = "pending_owner_approval"
            recipient.suppression_reason = "owner_approval_missing_at_dispatch"
            blocked += 1
            db.commit()
            continue

        fresh = evaluate_contact(db, principal, lead, "sms", recipient.contact, timezone_name)
        recipient.evidence = {
            **(recipient.evidence or {}),
            "fresh_compliance_decision_id": fresh["decision_id"],
            "fresh_compliance_at": datetime.now(timezone.utc).isoformat(),
            "fresh_compliance_reasons": fresh.get("reasons") or [],
        }
        if not fresh["allowed"]:
            recipient.status = "blocked_at_dispatch"
            recipient.suppression_reason = ",".join(fresh.get("reasons") or []) or "fresh_compliance_blocked"
            request.status = "blocked"
            request.error = f"Fresh compliance blocked dispatch: {recipient.suppression_reason}"
            blocked += 1
            db.commit()
            results.append({
                "recipient_id": recipient.id,
                "request_id": request.id,
                "status": "blocked_at_dispatch",
                "reasons": fresh.get("reasons") or [],
            })
            continue

        # Bind the request to the just-created decision. The controlled outbound
        # gateway independently validates that this exact decision is allowed,
        # matches the contact/channel, is still within its TTL, and that no new
        # suppression appeared before it calls Bland.
        request.compliance_decision_id = fresh["decision_id"]
        db.commit()
        try:
            dispatch_result = await dispatch_outbound_request(request.id, principal, db)
            recipient.status = "dispatched"
            recipient.suppression_reason = None
            recipient.evidence = {
                **(recipient.evidence or {}),
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
                "provider": "bland",
                "provider_reference": dispatch_result.get("provider_reference"),
            }
            sent += 1
            db.commit()
            results.append({
                "recipient_id": recipient.id,
                "request_id": request.id,
                "status": dispatch_result.get("status"),
                "provider_reference": dispatch_result.get("provider_reference"),
            })
        except HTTPException as exc:
            recipient.status = "dispatch_failed"
            recipient.suppression_reason = str(exc.detail)
            failed += 1
            db.commit()
            results.append({
                "recipient_id": recipient.id,
                "request_id": request.id,
                "status": "dispatch_failed",
                "detail": str(exc.detail),
            })
            # Provider/service failures should stop the batch rather than fan
            # out repeated requests into an unhealthy downstream service.
            if exc.status_code >= 500:
                break

    remaining = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
        SmsCampaignRecipient.status == "approved_not_dispatched",
    )).all()
    if not remaining and sent and not failed:
        campaign.status = "dispatched"
    elif sent:
        campaign.status = "partially_dispatched"

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="sms_campaign_dispatch_batch",
        summary=f"Fresh-compliance dispatch processed for campaign {campaign.name}: {sent} sent, {blocked} blocked",
        metadata_json={
            "campaign_id": campaign.id,
            "evaluated": len(recipients),
            "sent": sent,
            "blocked": blocked,
            "failed": failed,
            "missing": missing,
            "remaining_approved": len(remaining),
            "provider": "bland",
            "fresh_compliance": True,
        },
    ))
    db.commit()
    return {
        "campaign_id": campaign.id,
        "evaluated": len(recipients),
        "sent": sent,
        "blocked_at_dispatch": blocked,
        "dispatch_failed": failed,
        "missing_or_needs_timezone": missing,
        "remaining_approved": len(remaining),
        "results": results,
        "provider": "bland",
        "fresh_compliance": True,
    }

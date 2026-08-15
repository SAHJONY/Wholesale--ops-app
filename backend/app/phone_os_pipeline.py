from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .auth_models import CrmActivity, FollowUpTask
from .background_jobs import BackgroundJob
from .models import Lead
from .voice_models import VoiceCall


def ensure_next_work(
    db: Session,
    principal: Principal,
    call: VoiceCall,
    qualification: dict[str, Any],
    score: dict[str, Any],
) -> dict[str, Any]:
    """Create the next supervised work item exactly once for a qualified call.

    This layer deliberately prepares work rather than dispatching communications,
    making offers, signing contracts, or moving money. Those remain behind the
    existing compliance/approval/execution gates.
    """
    if not call.lead_id:
        return {"follow_up_task_id": None, "acquisition_job_id": None, "reason": "call_not_linked_to_lead"}

    lead = db.get(Lead, call.lead_id)
    if not lead:
        return {"follow_up_task_id": None, "acquisition_job_id": None, "reason": "lead_missing"}

    evidence = dict(call.evidence or {})
    prior = evidence.get("phone_pipeline") if isinstance(evidence.get("phone_pipeline"), dict) else {}
    if prior.get("prepared"):
        return {
            "follow_up_task_id": prior.get("follow_up_task_id"),
            "acquisition_job_id": prior.get("acquisition_job_id"),
            "reason": "already_prepared",
        }

    hot = bool(score.get("hot_lead"))
    title = "Call hot seller / review Phone OS handoff" if hot else "Follow up on seller phone qualification"
    due_at = datetime.now(timezone.utc) + (timedelta(hours=1) if hot else timedelta(days=3))
    task = FollowUpTask(
        organization_id=principal.organization_id,
        lead_id=lead.id,
        assigned_user_id=principal.user_id if hot else None,
        title=title,
        status="open",
        priority=95 if hot else 55,
        due_at=due_at,
        notes=(
            f"Phone OS captured {score.get('pillars_captured', 0)}/4 pillars. "
            "Seller statements remain unverified until public/property evidence confirms them."
        ),
    )
    db.add(task)
    db.flush()

    acquisition_job_id = None
    if hot:
        job = BackgroundJob(
            organization_id=principal.organization_id,
            job_type="acquisition_lead",
            status="queued",
            priority=90,
            payload_json={
                "lead_id": lead.id,
                "force": False,
                "trigger": "phone_os_hot_lead",
                "call_id": call.id,
            },
            created_by_user_id=principal.user_id,
        )
        db.add(job)
        db.flush()
        acquisition_job_id = job.id

    evidence["phone_pipeline"] = {
        "prepared": True,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "follow_up_task_id": task.id,
        "acquisition_job_id": acquisition_job_id,
        "human_review_required": True,
        "autonomous_offer_allowed": False,
        "autonomous_contract_allowed": False,
    }
    call.evidence = evidence

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="phone_pipeline_prepared",
        summary=(
            "Hot seller routed to human review and acquisition verification"
            if hot else "Seller routed to supervised follow-up"
        ),
        metadata_json={
            "call_id": call.id,
            "follow_up_task_id": task.id,
            "acquisition_job_id": acquisition_job_id,
            "hot_lead": hot,
            "pillars_captured": score.get("pillars_captured", 0),
            "seller_claims_unverified": True,
        },
    ))
    return {
        "follow_up_task_id": task.id,
        "acquisition_job_id": acquisition_job_id,
        "reason": "prepared",
    }


def pipeline_snapshot(db: Session, principal: Principal) -> dict[str, Any]:
    calls = db.scalars(select(VoiceCall).where(
        VoiceCall.organization_id == principal.organization_id,
    ).order_by(VoiceCall.created_at.desc()).limit(250)).all()
    qualified = [row for row in calls if isinstance((row.evidence or {}).get("phone_qualification"), dict)]
    hot = [row for row in qualified if bool(((row.evidence or {}).get("phone_qualification") or {}).get("hot_lead"))]
    unqualified = [row for row in calls if row.transcript_excerpt and row not in qualified]
    tasks = db.scalars(select(FollowUpTask).where(
        FollowUpTask.organization_id == principal.organization_id,
        FollowUpTask.status.in_(["open", "pending"]),
    )).all()
    return {
        "calls": len(calls),
        "qualified": len(qualified),
        "hot": len(hot),
        "pending_qualification": len(unqualified),
        "open_followups": len(tasks),
    }

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .background_jobs import BackgroundJob
from .database import get_db
from .models import Lead

router = APIRouter(prefix="/agentic-voice", tags=["agentic voice brain"])

REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL") or "gpt-realtime"
REALTIME_VOICE = os.getenv("OPENAI_REALTIME_VOICE") or "marin"
HUMAN_TRANSFER = os.getenv("VOICE_HUMAN_TRANSFER_TARGET") or "+12816628581"

# Tool names are deliberately narrow. No offer, contract, payment, title-clearance,
# or outbound-dispatch tool is exposed to the model.
SAFE_TOOL_NAMES = (
    "get_lead_context",
    "save_seller_pillars",
    "create_follow_up",
    "request_underwriting",
    "escalate_to_human",
)
BLOCKED_CAPABILITIES = (
    "binding_offer",
    "contract_execution",
    "money_movement",
    "title_clearance",
    "autonomous_outbound_dispatch",
)


def _linked(db: Session, principal: Principal, lead_id: int) -> Lead:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    lead = db.get(Lead, lead_id)
    if not linked or not lead:
        raise HTTPException(404, "Lead not found in this workspace")
    return lead


def realtime_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "get_lead_context",
            "description": "Read the current SAHJONY lead context. Treat seller statements as claims until verified.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {"lead_id": {"type": "integer"}}, "required": ["lead_id"],
            },
        },
        {
            "type": "function",
            "name": "save_seller_pillars",
            "description": "Save explicit seller-stated Motivation, Timeline, Condition and Price. Never infer missing values.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "lead_id": {"type": "integer"},
                    "motivation": {"type": ["string", "null"]},
                    "timeline_days": {"type": ["integer", "null"]},
                    "condition": {"type": ["string", "null"]},
                    "seller_price": {"type": ["number", "null"]},
                    "summary": {"type": "string"},
                },
                "required": ["lead_id", "motivation", "timeline_days", "condition", "seller_price", "summary"],
            },
        },
        {
            "type": "function",
            "name": "create_follow_up",
            "description": "Create a supervised CRM follow-up task. This does not contact the seller.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "lead_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 100},
                    "notes": {"type": "string"},
                },
                "required": ["lead_id", "title", "priority", "notes"],
            },
        },
        {
            "type": "function",
            "name": "request_underwriting",
            "description": "Queue source-backed acquisition verification/underwriting work. Does not create or communicate an offer.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {"lead_id": {"type": "integer"}, "reason": {"type": "string"}},
                "required": ["lead_id", "reason"],
            },
        },
        {
            "type": "function",
            "name": "escalate_to_human",
            "description": "Request transfer/handoff to the configured human acquisitions number.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "properties": {"lead_id": {"type": ["integer", "null"]}, "reason": {"type": "string"}},
                "required": ["lead_id", "reason"],
            },
        },
    ]


def session_instructions() -> str:
    return (
        "You are SAHJONY's bilingual English/Spanish acquisition voice agent for U.S. wholesale real estate. "
        "Your mission is to understand the seller and gather explicit Motivation, Timeline, Condition and Price, while staying natural and concise. "
        "Never invent ownership, liens, ARV, comps, repairs, title status, legal outcomes, or seller facts. Seller statements remain unverified claims. "
        "Use tools to save facts, create supervised follow-up, request source-backed underwriting, or escalate to a human. "
        "Immediately honor any do-not-call request and end the sales conversation. "
        "Never make a binding offer, execute a contract, move money, claim title is clear, or initiate outbound contact autonomously. "
        "If the seller requests a human, presents legal/title complexity, wants creative-finance terms, or is highly motivated, escalate to the human acquisitions target."
    )


@router.get("/blueprint")
def blueprint(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "model": REALTIME_MODEL,
        "voice": REALTIME_VOICE,
        "human_transfer_target": HUMAN_TRANSFER,
        "languages": ["en", "es"],
        "tools": realtime_tools(),
        "blocked_capabilities": list(BLOCKED_CAPABILITIES),
        "instructions": session_instructions(),
        "realtime_session": {
            "type": "realtime",
            "model": REALTIME_MODEL,
            "voice": REALTIME_VOICE,
            "instructions": session_instructions(),
            "tools": realtime_tools(),
            "tool_choice": "auto",
        },
    }


@router.post("/tools/{tool_name}")
def execute_tool(
    tool_name: str,
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    if tool_name not in SAFE_TOOL_NAMES:
        raise HTTPException(403, "Voice tool is not authorized")

    lead_id_raw = payload.get("lead_id")
    lead_id = int(lead_id_raw) if lead_id_raw not in (None, "") else None
    lead = _linked(db, principal, lead_id) if lead_id else None

    if tool_name == "get_lead_context":
        assert lead is not None
        return {
            "lead_id": lead.id,
            "seller_name": lead.seller_name,
            "status": lead.status,
            "state": getattr(lead, "state", None),
            "motivation_score": getattr(lead, "motivation_score", None),
            "timeline_days": getattr(lead, "timeline_days", None),
            "facts_boundary": "workspace facts plus seller-stated claims; verify property/owner/underwriting separately",
        }

    if tool_name == "save_seller_pillars":
        assert lead is not None
        timeline = payload.get("timeline_days")
        if timeline is not None:
            lead.timeline_days = int(timeline)
        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            lead_id=lead.id,
            activity_type="voice_seller_pillars_saved",
            summary="Seller-stated wholesale qualification pillars captured by voice agent",
            metadata_json={
                "motivation": payload.get("motivation"), "timeline_days": timeline,
                "condition": payload.get("condition"), "seller_price": payload.get("seller_price"),
                "summary": payload.get("summary"), "facts_are_seller_stated": True,
                "verified_property_facts": False,
            },
        ))
        db.commit()
        return {"saved": True, "lead_id": lead.id, "verified_property_facts": False}

    if tool_name == "create_follow_up":
        assert lead is not None
        task = FollowUpTask(
            organization_id=principal.organization_id,
            lead_id=lead.id,
            assigned_user_id=principal.user_id,
            title=str(payload.get("title") or "Seller follow-up")[:220],
            status="open",
            priority=max(1, min(100, int(payload.get("priority") or 50))),
            notes=str(payload.get("notes") or "")[:4000] or None,
        )
        db.add(task); db.commit(); db.refresh(task)
        return {"created": True, "follow_up_task_id": task.id, "dispatch_performed": False}

    if tool_name == "request_underwriting":
        assert lead is not None
        existing = db.scalar(select(BackgroundJob).where(
            BackgroundJob.organization_id == principal.organization_id,
            BackgroundJob.job_type == "acquisition_lead",
            BackgroundJob.status.in_(["queued", "retry", "running"]),
        ))
        if existing and int((existing.payload_json or {}).get("lead_id") or 0) == lead.id:
            return {"queued": True, "job_id": existing.id, "duplicate": True, "offer_created": False}
        job = BackgroundJob(
            organization_id=principal.organization_id,
            job_type="acquisition_lead",
            priority=90,
            payload_json={"lead_id": lead.id, "force": False, "source": "agentic_voice", "reason": payload.get("reason")},
            created_by_user_id=principal.user_id,
        )
        db.add(job); db.commit(); db.refresh(job)
        return {"queued": True, "job_id": job.id, "offer_created": False}

    # escalate_to_human
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id if lead else None,
        activity_type="voice_human_escalation_requested",
        summary="Voice agent requested human acquisitions handoff",
        metadata_json={"reason": payload.get("reason"), "target": HUMAN_TRANSFER},
    ))
    db.commit()
    return {"escalate": True, "transfer_target": HUMAN_TRANSFER, "binding_action": False}

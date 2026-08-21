from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead
from .voice_engine import requires_all_party_consent
from .voice_models import VoiceCall

router = APIRouter(prefix="/voice-intelligence", tags=["voice intelligence"])

VOICE_MEMORY_TYPES = (
    "voice_seller_pillars_saved",
    "phone_call_qualified",
    "voice_human_escalation_requested",
    "voice_call_inbound",
)


def _lead(db: Session, principal: Principal, lead_id: int) -> Lead:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    lead = db.get(Lead, lead_id)
    if not linked or not lead:
        raise HTTPException(404, "Lead not found in this workspace")
    return lead


def seller_memory(db: Session, principal: Principal, lead_id: int) -> dict[str, Any]:
    lead = _lead(db, principal, lead_id)
    activities = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.lead_id == lead_id,
        CrmActivity.activity_type.in_(VOICE_MEMORY_TYPES),
    ).order_by(CrmActivity.created_at.desc()).limit(50)).all()

    latest_pillars: dict[str, Any] = {}
    human_escalations: list[dict[str, Any]] = []
    for activity in activities:
        meta = activity.metadata_json or {}
        if activity.activity_type == "voice_seller_pillars_saved" and not latest_pillars:
            latest_pillars = {
                "motivation": meta.get("motivation"),
                "timeline_days": meta.get("timeline_days"),
                "condition": meta.get("condition"),
                "seller_price": meta.get("seller_price"),
                "summary": meta.get("summary"),
                "facts_are_seller_stated": True,
                "verified_property_facts": False,
            }
        elif activity.activity_type == "phone_call_qualified" and not latest_pillars:
            qualification = meta.get("qualification") or {}
            latest_pillars = {
                "motivation": qualification.get("motivation"),
                "timeline_days": qualification.get("timeline_days"),
                "condition": qualification.get("condition"),
                "seller_price": qualification.get("seller_price"),
                "summary": qualification.get("summary"),
                "facts_are_seller_stated": True,
                "verified_property_facts": False,
            }
        if activity.activity_type == "voice_human_escalation_requested":
            human_escalations.append({
                "reason": meta.get("reason"),
                "target": meta.get("target"),
                "created_at": activity.created_at,
            })

    prop = lead.property
    property_context = None
    if prop:
        property_context = {
            "property_id": prop.id,
            "address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
            "property_type": prop.property_type,
            "asking_price": prop.asking_price,
            "arv": prop.arv,
            "repairs": prop.repairs,
            "mao": prop.mao,
            "boundary": "workspace values only; provenance/verification must be checked before presenting as verified facts",
        }

    return {
        "lead_id": lead.id,
        "seller_name": lead.seller_name,
        "lead_status": lead.status,
        "motivation_score": lead.motivation_score,
        "timeline_days": lead.timeline_days,
        "latest_seller_pillars": latest_pillars or None,
        "property_context": property_context,
        "prior_human_escalations": human_escalations[:10],
        "voice_activity_count": len(activities),
        "memory_source": "tenant-scoped CRM/evidence ledger",
        "memory_boundary": "seller statements remain claims until independently verified",
    }


def jurisdiction_policy(state: str | None, direction: str | None = None) -> dict[str, Any]:
    normalized = str(state or "").strip().upper()
    unknown = len(normalized) != 2
    all_party = True if unknown else requires_all_party_consent(normalized)
    policy: dict[str, Any] = {
        "state": normalized or None,
        "direction": direction or None,
        "state_known": not unknown,
        "recording_policy": "explicit_all_party_consent_required" if all_party else "one_party_state_but_system_disclosure_and_recorded_basis_required",
        "all_party_consent_treated_as_required": all_party,
        "recording_default": False,
        "ai_identity_disclosure_required_by_system": True,
        "outbound_requires_compliance_decision": True,
        "outbound_requires_human_approval": True,
        "autonomous_outbound_dispatch": False,
        "discovery_allowed": not unknown,
        "owner_deed_verification_allowed": not unknown,
        "underwriting_allowed": not unknown,
        "outreach_policy": "apply_state_and_federal_compliance_gate",
        "rules_status": "state_baseline_requires_current_legal_validation" if not unknown else "blocked_state_unknown",
        "legal_boundary": "operational safety policy, not legal advice or a substitute for current jurisdiction-specific legal review",
        "fail_closed_reason": "state_unknown" if unknown else None,
    }
    if normalized == "TX":
        policy.update({
            "rules_status": "texas_operational_profile_verified_2026_08_15",
            "discovery_allowed": True,
            "owner_deed_verification_allowed": True,
            "underwriting_allowed": True,
            "outreach_policy": "allowed_only_after_federal_dnc_and_texas_compliance_decision_plus_human_approval",
            "conservative_calling_window_local": {
                "monday_saturday": "09:00-21:00",
                "sunday": "12:00-21:00",
            },
            "caller_identification_required": ["caller_name", "business_name", "purpose_of_call"],
            "mobile_call_consent_rule": "do_not_place_prohibited_solicitation_calls_to_chargeable_mobile_numbers_without_required_consent; compliance engine must decide applicability",
            "recording_policy": "texas_one_party_rule_noted; system still requires AI disclosure and documented recording basis",
            "recording_default": False,
            "authorities": [
                "Texas Business & Commerce Code Chapter 301, including Sec. 301.051",
                "Texas Business & Commerce Code Chapter 305, including Sec. 305.001",
                "Texas Penal Code Chapter 16 interception exceptions/consent provisions",
            ],
        })
    return policy


def call_qa(call: VoiceCall) -> dict[str, Any]:
    evidence = call.evidence or {}
    qualification = evidence.get("phone_qualification") or {}
    pillars = sum(1 for key in ("motivation", "timeline_days", "condition", "seller_price") if qualification.get(key) not in (None, ""))

    checks = {
        "ai_disclosure": bool(call.ai_disclosed),
        "transcript_present": bool(str(call.transcript_excerpt or "").strip()),
        "qualification_present": bool(qualification),
        "all_four_pillars": pillars == 4,
        "opt_out_detected": bool(call.verbal_opt_out),
        "recording_has_basis": (not call.recorded) or bool(call.recording_consent_basis),
    }
    weighted = (
        (25 if checks["ai_disclosure"] else 0)
        + (15 if checks["transcript_present"] else 0)
        + (20 if checks["qualification_present"] else 0)
        + (20 * pillars / 4)
        + (20 if checks["recording_has_basis"] else 0)
    )
    blockers: list[str] = []
    if not checks["ai_disclosure"]:
        blockers.append("ai_disclosure_not_recorded")
    if call.recorded and not call.recording_consent_basis:
        blockers.append("recording_without_recorded_consent_basis")
    if not checks["transcript_present"]:
        blockers.append("missing_transcript")

    return {
        "call_id": call.id,
        "score": round(float(weighted), 1),
        "grade": "A" if weighted >= 90 else "B" if weighted >= 80 else "C" if weighted >= 70 else "D" if weighted >= 60 else "F",
        "pillars_captured": pillars,
        "checks": checks,
        "blockers": blockers,
        "needs_review": bool(blockers) or weighted < 80,
        "quality_boundary": "deterministic operational QA; it does not certify legal compliance or seller truthfulness",
    }


@router.get("/memory/{lead_id}")
def memory(lead_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return seller_memory(db, principal, lead_id)


@router.get("/policy/{lead_id}")
def policy(lead_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead = _lead(db, principal, lead_id)
    state = lead.property.state if lead.property else None
    return jurisdiction_policy(state)


@router.get("/calls/{call_id}/qa")
def qa(call_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    call = db.get(VoiceCall, call_id)
    if not call or call.organization_id != principal.organization_id:
        raise HTTPException(404, "Voice call not found")
    return call_qa(call)


@router.get("/brief/{lead_id}")
def realtime_brief(lead_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    memory_payload = seller_memory(db, principal, lead_id)
    state = (memory_payload.get("property_context") or {}).get("state")
    return {
        "memory": memory_payload,
        "policy": jurisdiction_policy(state),
        "agent_rules": {
            "languages": ["en", "es"],
            "never_invent_property_facts": True,
            "never_create_binding_offer": True,
            "never_execute_contract": True,
            "never_move_money": True,
            "human_escalation_for_complexity": True,
        },
    }

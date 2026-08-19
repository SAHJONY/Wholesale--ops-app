from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead
from .outbound_models import OutboundRequest
from .sms_campaign_models import SmsAppointmentRequest, SmsCampaign
from .sms_models import SmsMessage
from .voice_models import VoiceCall

router = APIRouter(prefix="/communication-os", tags=["communication operating system"])

# Communication is language-aware independently of the UI translation layer.
# A seller/buyer may speak any supported language while addresses, money,
# legal instrument identifiers, phone numbers and compliance evidence remain
# verbatim and are never machine-translated as factual records.
LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "direction": "ltr"},
    "es": {"name": "Español", "direction": "ltr"},
    "pt": {"name": "Português", "direction": "ltr"},
    "fr": {"name": "Français", "direction": "ltr"},
    "ht": {"name": "Kreyòl ayisyen", "direction": "ltr"},
    "de": {"name": "Deutsch", "direction": "ltr"},
    "it": {"name": "Italiano", "direction": "ltr"},
    "nl": {"name": "Nederlands", "direction": "ltr"},
    "pl": {"name": "Polski", "direction": "ltr"},
    "ro": {"name": "Română", "direction": "ltr"},
    "ru": {"name": "Русский", "direction": "ltr"},
    "uk": {"name": "Українська", "direction": "ltr"},
    "ar": {"name": "العربية", "direction": "rtl"},
    "he": {"name": "עברית", "direction": "rtl"},
    "fa": {"name": "فارسی", "direction": "rtl"},
    "ur": {"name": "اردو", "direction": "rtl"},
    "hi": {"name": "हिन्दी", "direction": "ltr"},
    "bn": {"name": "বাংলা", "direction": "ltr"},
    "pa": {"name": "ਪੰਜਾਬੀ", "direction": "ltr"},
    "gu": {"name": "ગુજરાતી", "direction": "ltr"},
    "zh": {"name": "中文", "direction": "ltr"},
    "ja": {"name": "日本語", "direction": "ltr"},
    "ko": {"name": "한국어", "direction": "ltr"},
    "vi": {"name": "Tiếng Việt", "direction": "ltr"},
    "tl": {"name": "Tagalog", "direction": "ltr"},
    "id": {"name": "Bahasa Indonesia", "direction": "ltr"},
    "tr": {"name": "Türkçe", "direction": "ltr"},
    "sw": {"name": "Kiswahili", "direction": "ltr"},
    "yo": {"name": "Yorùbá", "direction": "ltr"},
}

PERSONAS: dict[str, dict[str, Any]] = {
    "acquisitions": {
        "label": "SAHJONY Acquisitions",
        "mission": "Earn permission, understand the seller, and capture explicit Motivation, Timeline, Condition and Price.",
        "tone": ["empathetic", "professional", "consultative", "concise", "non-pressuring"],
        "never": ["invent ownership", "quote an unapproved binding offer", "argue with the seller", "hide material facts"],
        "handoff": ["high motivation", "legal/title complexity", "creative finance request", "seller requests human"],
    },
    "negotiation": {
        "label": "SAHJONY Negotiation",
        "mission": "Explore price and terms inside approved underwriting boundaries without disclosing internal formulas unnecessarily.",
        "tone": ["calm", "curious", "numbers-aware", "respectful"],
        "never": ["exceed approved MAO", "misrepresent ARV or repairs", "create false urgency", "make binding promises without approval"],
        "handoff": ["price above walkaway", "creative structure", "material fact conflict"],
    },
    "follow_up": {
        "label": "SAHJONY Seller Follow-Up",
        "mission": "Continue the relationship from memory without repeating answered questions and surface meaningful changes.",
        "tone": ["warm", "brief", "context-aware", "respectful"],
        "never": ["spam", "ignore opt-out", "restart qualification from zero", "manufacture urgency"],
        "handoff": ["seller ready now", "material timeline change", "new title/legal issue"],
    },
    "disposition": {
        "label": "SAHJONY Dispositions",
        "mission": "Communicate verified deal economics to qualified buyers and obtain price, timing and proof-of-funds evidence.",
        "tone": ["metric-driven", "direct", "professional", "investor-focused"],
        "never": ["claim POF exists when absent", "invent comps", "hide assignment terms", "call a candidate deal-ready without verification"],
        "handoff": ["buyer price commitment", "POF submitted", "access request", "contractual question"],
    },
    "transaction": {
        "label": "SAHJONY Transaction Coordination",
        "mission": "Keep contract-to-close communication factual, timely and traceable across seller, buyer and title.",
        "tone": ["precise", "neutral", "deadline-aware", "service-oriented"],
        "never": ["give legal advice", "declare title clear without title evidence", "alter contract terms", "move money autonomously"],
        "handoff": ["title exception", "payoff discrepancy", "closing document issue", "deadline risk"],
    },
}

CHANNELS = {
    "sms": {"provider": "bland", "approval_required": True, "compliance_required": True},
    "automated_call": {"provider": "bland", "approval_required": True, "compliance_required": True, "record": False},
    "business_email": {"provider": "resend", "authorization_basis_required": True},
    "appointment": {"provider": "internal", "seller_confirmation_required": True},
}

PROTECTED_FACT_TYPES = (
    "street address", "phone number", "email address", "price", "ARV", "repair estimate", "APN",
    "legal description", "instrument number", "lien/payoff", "contract terms", "compliance evidence",
)


def _linked_lead(db: Session, principal: Principal, lead_id: int) -> Lead:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    lead = db.get(Lead, lead_id)
    if not linked or not lead:
        raise HTTPException(404, "Lead not found in this workspace")
    return lead


def _env_ready() -> dict[str, bool]:
    return {
        "bland_api_key": bool(os.getenv("BLAND_AI_API_KEY")),
        "bland_phone": bool(os.getenv("BLAND_SMS_AGENT_NUMBER") or os.getenv("BLAND_MESSAGING_NUMBER") or os.getenv("BLAND_DEFAULT_FROM_NUMBER") or os.getenv("BLAND_DEFAULT_CALLER_ID")),
        "resend_api_key": bool(os.getenv("RESEND_API_KEY")),
        "email_domain_verified": str(os.getenv("EMAIL_DOMAIN_VERIFIED") or "").lower() == "true",
        "email_inbound_verified": str(os.getenv("EMAIL_INBOUND_VERIFIED") or "").lower() == "true",
        "resend_webhook_secret": bool(os.getenv("RESEND_WEBHOOK_SECRET")),
    }


def _count(db: Session, model, organization_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(model.organization_id == organization_id)) or 0)


@router.get("/blueprint")
def blueprint(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "version": "10.0",
        "operating_model": "permission -> understand -> qualify -> verify -> underwrite -> options -> respectful follow-up",
        "personas": PERSONAS,
        "channels": CHANNELS,
        "languages": LANGUAGES,
        "translation_policy": {
            "communication_language_is_independent_from_ui_language": True,
            "translate_intent_not_facts": True,
            "protected_fact_types": list(PROTECTED_FACT_TYPES),
            "preserve_opt_out_meaning_exactly": True,
            "fallback_language": "en",
        },
        "hard_gates": [
            "verified contact/identity according to owner-resolution policy",
            "channel-specific compliance decision",
            "active suppression re-check at dispatch",
            "owner approval for automated seller outreach",
            "no autonomous binding offer, contract execution, money movement or title clearance",
        ],
    }


@router.get("/readiness")
def readiness(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    env = _env_ready()
    counts = {
        "sms_messages": _count(db, SmsMessage, principal.organization_id),
        "voice_calls": _count(db, VoiceCall, principal.organization_id),
        "outbound_requests": _count(db, OutboundRequest, principal.organization_id),
        "sms_campaigns": _count(db, SmsCampaign, principal.organization_id),
        "appointment_requests": _count(db, SmsAppointmentRequest, principal.organization_id),
    }
    sms_live = env["bland_api_key"] and env["bland_phone"]
    voice_live = env["bland_api_key"] and env["bland_phone"]
    email_send_live = env["resend_api_key"] and env["email_domain_verified"]
    email_reply_live = email_send_live and env["email_inbound_verified"] and env["resend_webhook_secret"]
    proven = {
        "sms": counts["sms_messages"] > 0,
        "voice": counts["voice_calls"] > 0,
        "outbound_gateway": counts["outbound_requests"] > 0,
        "campaign": counts["sms_campaigns"] > 0,
        "appointment": counts["appointment_requests"] > 0,
    }
    return {
        "generated_at": datetime.now(timezone.utc),
        "provider_configuration": {
            "sms_live": sms_live,
            "voice_live": voice_live,
            "email_send_live": email_send_live,
            "email_reply_live": email_reply_live,
            "checks": env,
        },
        "production_evidence": counts,
        "proven_live": proven,
        "production_proven": all((proven["sms"], proven["voice"], proven["outbound_gateway"])),
        "next_proof": [
            "one approved compliant Bland SMS with provider reference and reply capture",
            "one approved non-recorded Bland call with outcome persistence",
            "one authorized departmental email with delivery/inbound reply proof",
            "one seller-confirmed appointment persisted to CRM",
        ],
    }


@router.get("/scorecard")
def scorecard(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    sms_total = _count(db, SmsMessage, principal.organization_id)
    voice_total = _count(db, VoiceCall, principal.organization_id)
    requests_total = _count(db, OutboundRequest, principal.organization_id)
    campaigns_total = _count(db, SmsCampaign, principal.organization_id)
    appointments_total = _count(db, SmsAppointmentRequest, principal.organization_id)

    inbound_sms = int(db.scalar(select(func.count()).select_from(SmsMessage).where(
        SmsMessage.organization_id == principal.organization_id, SmsMessage.direction == "inbound")) or 0)
    outbound_sms = int(db.scalar(select(func.count()).select_from(SmsMessage).where(
        SmsMessage.organization_id == principal.organization_id, SmsMessage.direction == "outbound")) or 0)
    opt_outs = int(db.scalar(select(func.count()).select_from(SmsMessage).where(
        SmsMessage.organization_id == principal.organization_id, SmsMessage.triggered_opt_out.is_(True))) or 0)
    completed_calls = int(db.scalar(select(func.count()).select_from(VoiceCall).where(
        VoiceCall.organization_id == principal.organization_id, VoiceCall.status.in_(["completed", "ended"]))) or 0)

    return {
        "generated_at": datetime.now(timezone.utc),
        "activity": {
            "outbound_requests": requests_total,
            "sms_total": sms_total,
            "sms_outbound": outbound_sms,
            "sms_inbound": inbound_sms,
            "voice_calls": voice_total,
            "completed_calls": completed_calls,
            "campaigns": campaigns_total,
            "appointments": appointments_total,
            "opt_outs": opt_outs,
        },
        "conversion": {
            "sms_reply_rate_pct": round(inbound_sms / outbound_sms * 100, 1) if outbound_sms else None,
            "call_completion_rate_pct": round(completed_calls / voice_total * 100, 1) if voice_total else None,
            "appointment_per_outbound_pct": round(appointments_total / requests_total * 100, 1) if requests_total else None,
        },
        "management_rule": "Optimize verified conversations, appointments, contracts, closes and assignment revenue — not raw message volume.",
    }


@router.post("/leads/{lead_id}/plan")
def communication_plan(
    lead_id: int,
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    lead = _linked_lead(db, principal, lead_id)
    persona = str(payload.get("persona") or "acquisitions").strip().lower()
    if persona not in PERSONAS:
        raise HTTPException(422, "Unsupported communication persona")
    language = str(payload.get("language") or "en").strip().lower()
    if language not in LANGUAGES:
        language = "en"
    channel = str(payload.get("channel") or "sms").strip().lower()
    if channel not in CHANNELS:
        raise HTTPException(422, "Unsupported communication channel")

    plan = {
        "lead_id": lead.id,
        "seller_name": lead.seller_name,
        "persona": persona,
        "persona_config": PERSONAS[persona],
        "language": language,
        "language_name": LANGUAGES[language]["name"],
        "channel": channel,
        "provider": CHANNELS[channel]["provider"],
        "objective": str(payload.get("objective") or PERSONAS[persona]["mission"]),
        "memory_first": True,
        "preserve_verified_facts_verbatim": True,
        "dispatch_performed": False,
        "required_before_dispatch": [
            "resolve exact contact and identity gate",
            "evaluate channel/jurisdiction compliance",
            "check suppression immediately before dispatch",
            "obtain required owner approval",
        ] if channel in {"sms", "automated_call"} else ["document authorization basis"],
    }
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="communication_plan_created",
        summary=f"{PERSONAS[persona]['label']} {channel} plan prepared in {LANGUAGES[language]['name']}",
        metadata_json=plan,
    ))
    db.commit()
    return plan

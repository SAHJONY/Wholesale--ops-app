"""Agentic seller-SMS orchestration for wholesale acquisitions.

The agents in this module may classify, extract, score, draft, route and queue
work. They do not bypass the existing compliance, suppression, quiet-hours or
owner-approval gates. Any outbound draft still has to pass ``/sms/preflight``,
``/compliance/evaluate`` and the controlled outbound gateway before delivery.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .autonomy import create_task
from .compliance import normalize_phone
from .database import get_db
from .models import Lead
from .sms_agentic_models import SmsConversationState
from .sms_engine import classify_inbound, suppress
from .sms_models import SmsMessage

router = APIRouter(prefix="/sms-agent", tags=["agentic sms acquisitions"])
logger = logging.getLogger(__name__)

MAX_CONTEXT_MESSAGES = 20

QUALIFICATION_KEYS = (
    "motivation",
    "timeline_days",
    "asking_price",
    "occupancy",
    "condition",
    "repairs",
    "decision_makers",
    "mortgage_or_liens",
    "appointment_preference",
    "seller_goal",
)

AGENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent", "stage", "confidence", "lead_temperature", "opportunity_score",
        "qualification", "reply_draft", "next_action", "follow_up_days",
        "requires_human", "escalation_reason", "evidence",
    ],
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "interested", "not_interested", "question", "negotiation",
                "appointment", "call_request", "wrong_number", "opt_out",
                "hostile", "unclear",
            ],
        },
        "stage": {
            "type": "string",
            "enum": [
                "new", "engaged", "qualifying", "qualified", "appointment_ready",
                "negotiating", "nurture", "dead", "suppressed",
            ],
        },
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "lead_temperature": {"type": "string", "enum": ["hot", "warm", "nurture", "dead"]},
        "opportunity_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "qualification": {
            "type": "object",
            "additionalProperties": False,
            "required": list(QUALIFICATION_KEYS),
            "properties": {
                "motivation": {"type": ["string", "null"]},
                "timeline_days": {"type": ["integer", "null"]},
                "asking_price": {"type": ["number", "null"]},
                "occupancy": {"type": ["string", "null"]},
                "condition": {"type": ["string", "null"]},
                "repairs": {"type": ["array", "null"], "items": {"type": "string"}},
                "decision_makers": {"type": ["string", "null"]},
                "mortgage_or_liens": {"type": ["string", "null"]},
                "appointment_preference": {"type": ["string", "null"]},
                "seller_goal": {"type": ["string", "null"]},
            },
        },
        "reply_draft": {"type": ["string", "null"]},
        "next_action": {
            "type": "string",
            "enum": [
                "ask_question", "prepare_call", "book_appointment", "underwrite",
                "negotiate", "nurture", "suppress", "human_review", "close_conversation",
            ],
        },
        "follow_up_days": {"type": ["integer", "null"]},
        "requires_human": {"type": "boolean"},
        "escalation_reason": {"type": ["string", "null"]},
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short seller statements that support the extraction. Never invent evidence.",
        },
    },
}

SYSTEM_PROMPT = """You are the seller-conversation brain for a supervised real-estate wholesale acquisition desk.

Your job is to classify the seller's latest SMS, extract only facts the seller actually stated, update qualification state, score opportunity, and draft one concise next reply.

Hard boundaries:
- Never claim a property value, title status, lien status, legal authority, available funds, closing certainty, or offer approval unless that exact fact is supplied.
- Never pressure a seller because of foreclosure, probate, taxes, age, disability, family death, immigration status, or any other vulnerable circumstance.
- Never threaten, deceive, impersonate, or hide that the sender is a real-estate investment business.
- Never treat silence or ambiguity as consent.
- If the seller asks to stop, says it is a wrong number, is hostile, asks for legal advice, or raises a material dispute, route away from autonomous reply.
- Do not send anything. You only draft and recommend. Delivery remains behind deterministic compliance and human approval gates.
- Qualification fields must contain seller-stated facts only. Unknown means null.
- Keep reply_draft conversational, short, one question at a time, and do not mention internal scoring, distress records, or automation.
"""


def _conversation(db: Session, principal: Principal, lead_id: int) -> SmsConversationState:
    row = db.scalar(select(SmsConversationState).where(
        SmsConversationState.organization_id == principal.organization_id,
        SmsConversationState.lead_id == lead_id,
    ))
    if row:
        return row
    row = SmsConversationState(organization_id=principal.organization_id, lead_id=lead_id)
    db.add(row)
    db.flush()
    return row


def _transcript(db: Session, principal: Principal, lead_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(SmsMessage).where(
        SmsMessage.organization_id == principal.organization_id,
        SmsMessage.lead_id == lead_id,
    ).order_by(SmsMessage.created_at.desc()).limit(MAX_CONTEXT_MESSAGES)).all()
    return [
        {
            "id": row.id,
            "direction": row.direction,
            "body": row.body,
            "created_at": row.created_at.isoformat(),
            "keyword": row.keyword,
        }
        for row in reversed(rows)
    ]


def _lead_context(lead: Lead) -> dict[str, Any]:
    prop = lead.property
    return {
        "lead": {
            "id": lead.id,
            "seller_name": lead.seller_name,
            "status": lead.status,
            "source": lead.source,
            "timeline_days": lead.timeline_days,
            "motivation_score": lead.motivation_score,
            "distress_score": lead.distress_score,
            "equity_score": lead.equity_score,
        },
        "property": {
            "address": prop.address if prop else None,
            "city": prop.city if prop else None,
            "state": prop.state if prop else None,
            "zip_code": prop.zip_code if prop else None,
            "asking_price": prop.asking_price if prop else None,
            "arv": prop.arv if prop else None,
            "repairs": prop.repairs if prop else None,
            "mao": prop.mao if prop else None,
            "distress_signals": prop.distress_signals if prop else [],
        },
    }


def _invoke_claude(payload: dict[str, Any]) -> dict[str, Any]:
    from .config import settings
    import anthropic

    if not settings.anthropic_api_key:
        raise RuntimeError("no_anthropic_api_key")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": AGENT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": "Analyze this seller conversation. Data absent from this payload is unknown.\n\n" + json.dumps(payload, default=str),
        }],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    result = json.loads(text)
    result["source"] = "claude"
    result["model"] = getattr(response, "model", settings.claude_model)
    return result


def _invoke_openai(payload: dict[str, Any]) -> dict[str, Any]:
    from .config import settings
    from openai import OpenAI

    if not settings.openai_api_key:
        raise RuntimeError("no_openai_api_key")
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Analyze this seller conversation. Data absent from this payload is unknown.\n\n" + json.dumps(payload, default=str)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "sms_seller_agent", "strict": True, "schema": AGENT_SCHEMA},
        },
    )
    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise RuntimeError("model_refusal")
    result = json.loads(choice.message.content or "{}")
    result["source"] = "openai"
    result["model"] = getattr(response, "model", settings.openai_model)
    return result


def _money(text: str) -> float | None:
    match = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _deterministic(latest: str) -> dict[str, Any]:
    text = (latest or "").strip()
    low = text.lower()
    kind, _ = classify_inbound(text)
    if kind == "opt_out":
        intent, stage, temp, score, action = "opt_out", "suppressed", "dead", 0, "suppress"
    elif any(token in low for token in ("wrong number", "not me", "don't own", "do not own")):
        intent, stage, temp, score, action = "wrong_number", "dead", "dead", 0, "close_conversation"
    elif any(token in low for token in ("not interested", "no thanks", "don't want to sell", "do not want to sell")):
        intent, stage, temp, score, action = "not_interested", "nurture", "dead", 5, "close_conversation"
    elif any(token in low for token in ("call me", "give me a call", "phone me")):
        intent, stage, temp, score, action = "call_request", "appointment_ready", "hot", 85, "prepare_call"
    elif any(token in low for token in ("yes", "interested", "offer", "sell", "how much")):
        intent, stage, temp, score, action = "interested", "qualifying", "warm", 60, "ask_question"
    else:
        intent, stage, temp, score, action = "unclear", "engaged", "nurture", 35, "human_review"

    asking = _money(text)
    qualification = {key: None for key in QUALIFICATION_KEYS}
    qualification["asking_price"] = asking
    return {
        "intent": intent,
        "stage": stage,
        "confidence": 45,
        "lead_temperature": temp,
        "opportunity_score": score,
        "qualification": qualification,
        "reply_draft": None if action in {"suppress", "close_conversation", "human_review"} else "Thanks for getting back to me. What would need to happen for selling the property to make sense for you?",
        "next_action": action,
        "follow_up_days": None,
        "requires_human": action in {"human_review", "prepare_call"},
        "escalation_reason": "deterministic_fallback" if action == "human_review" else None,
        "evidence": [text[:240]] if text else [],
        "source": "deterministic",
    }


def analyze_turn(payload: dict[str, Any], latest: str) -> dict[str, Any]:
    try:
        return _invoke_claude(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Claude SMS agent unavailable: %s", type(exc).__name__)
    try:
        return _invoke_openai(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI SMS agent unavailable: %s", type(exc).__name__)
    return _deterministic(latest)


def _merge_qualification(current: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current or {})
    for key in QUALIFICATION_KEYS:
        value = extracted.get(key)
        if value not in (None, "", []):
            merged[key] = value
        elif key not in merged:
            merged[key] = None
    return merged


def process_message(db: Session, principal: Principal, message: SmsMessage) -> dict[str, Any]:
    if message.organization_id != principal.organization_id:
        raise HTTPException(403, "Message is outside this workspace")
    if message.direction != "inbound":
        raise HTTPException(422, "Only inbound messages can be processed")
    if not message.lead_id:
        raise HTTPException(422, "Inbound message must be linked to a lead before agent processing")

    lead = db.get(Lead, message.lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    state = _conversation(db, principal, lead.id)

    if message.triggered_opt_out:
        state.stage = "suppressed"
        state.status = "suppressed"
        state.lead_temperature = "dead"
        state.opportunity_score = 0
        state.last_message_id = message.id
        state.last_analysis = {"intent": "opt_out", "source": "deterministic_suppression"}
        state.agent_plan = {"next_action": "suppress", "reply_draft": None, "requires_human": False}
        db.commit()
        return {"lead_id": lead.id, "stage": state.stage, "action": "suppressed", "reply_draft": None}

    payload = {
        **_lead_context(lead),
        "current_state": {
            "stage": state.stage,
            "lead_temperature": state.lead_temperature,
            "opportunity_score": state.opportunity_score,
            "qualification": state.qualification or {},
        },
        "conversation": _transcript(db, principal, lead.id),
        "latest_message_id": message.id,
    }
    result = analyze_turn(payload, message.body)

    state.stage = str(result.get("stage") or "engaged")
    state.status = "active" if state.stage not in {"dead", "suppressed"} else state.stage
    state.lead_temperature = str(result.get("lead_temperature") or "unscored")
    state.opportunity_score = int(max(0, min(100, int(result.get("opportunity_score") or 0))))
    state.qualification = _merge_qualification(state.qualification or {}, result.get("qualification") or {})
    state.agent_plan = {
        "next_action": result.get("next_action"),
        "reply_draft": result.get("reply_draft"),
        "follow_up_days": result.get("follow_up_days"),
        "requires_human": bool(result.get("requires_human")),
        "escalation_reason": result.get("escalation_reason"),
    }
    state.last_analysis = result
    state.last_message_id = message.id

    # Mirror only workflow state into the CRM. Seller-stated prices, repair
    # claims and lien statements stay in qualification JSON until verified by a
    # human or property-data source.
    if state.stage in {"qualified", "appointment_ready", "negotiating"}:
        lead.status = "qualified" if state.stage == "qualified" else state.stage

    if state.lead_temperature == "hot" or state.opportunity_score >= 80:
        create_task(
            db,
            "hot_seller_handoff",
            {
                "trigger": "sms_agent",
                "conversation_state_id": state.id,
                "opportunity_score": state.opportunity_score,
                "next_action": state.agent_plan.get("next_action"),
            },
            priority=100,
            lead_id=lead.id,
            requires_approval=False,
        )

    if result.get("reply_draft"):
        create_task(
            db,
            "review_sms_reply",
            {
                "trigger": "sms_agent",
                "conversation_state_id": state.id,
                "message_id": message.id,
                "draft": result.get("reply_draft"),
                "next_action": result.get("next_action"),
                "note": "Draft only. Must pass SMS preflight, compliance evaluation and outbound approval before dispatch.",
            },
            priority=95 if state.lead_temperature == "hot" else 70,
            lead_id=lead.id,
            requires_approval=True,
        )

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="sms_agent_turn",
        summary=f"AI SMS agent classified seller as {state.lead_temperature} / {state.stage}",
        metadata_json={
            "message_id": message.id,
            "source": result.get("source"),
            "intent": result.get("intent"),
            "opportunity_score": state.opportunity_score,
            "next_action": result.get("next_action"),
        },
    ))
    db.commit()
    return {
        "conversation_state_id": state.id,
        "lead_id": lead.id,
        "message_id": message.id,
        "intent": result.get("intent"),
        "stage": state.stage,
        "lead_temperature": state.lead_temperature,
        "opportunity_score": state.opportunity_score,
        "qualification": state.qualification,
        "agent_plan": state.agent_plan,
        "source": result.get("source"),
        "model": result.get("model"),
    }


@router.post("/inbound")
def agentic_inbound(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Record an inbound seller SMS and immediately run the acquisition agents.

    This is an authenticated internal orchestration endpoint. Provider webhooks
    should validate their provider signature and then call the same service
    logic with the resolved organization and lead.
    """
    lead_id = int(payload.get("lead_id") or 0)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    contact = normalize_phone(str(payload.get("from") or lead.phone or ""))
    body = str(payload.get("body") or "").strip()
    if not contact or not body:
        raise HTTPException(422, "from and body are required")

    kind, keyword = classify_inbound(body)
    message = SmsMessage(
        organization_id=principal.organization_id,
        lead_id=lead.id,
        direction="inbound",
        contact=contact,
        body=body,
        keyword=keyword or None,
        triggered_opt_out=kind == "opt_out",
        status="received",
        evidence={"classified_as": kind, "ingested_by": "sms_agent"},
    )
    db.add(message)
    db.flush()

    if kind == "opt_out":
        suppress(db, principal.organization_id, contact, "recipient_opt_out", f"sms_agent:{keyword}", lead.id)
    db.commit()
    db.refresh(message)
    return process_message(db, principal, message)


@router.post("/messages/{message_id}/process")
def process_existing_message(
    message_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    message = db.get(SmsMessage, message_id)
    if not message:
        raise HTTPException(404, "SMS message not found")
    return process_message(db, principal, message)


@router.get("/conversations")
def conversations(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(SmsConversationState).where(
        SmsConversationState.organization_id == principal.organization_id,
    ).order_by(SmsConversationState.updated_at.desc()).limit(200)).all()
    return [{
        "id": row.id,
        "lead_id": row.lead_id,
        "stage": row.stage,
        "status": row.status,
        "lead_temperature": row.lead_temperature,
        "opportunity_score": row.opportunity_score,
        "qualification": row.qualification,
        "agent_plan": row.agent_plan,
        "last_analysis": row.last_analysis,
        "last_message_id": row.last_message_id,
        "updated_at": row.updated_at,
    } for row in rows]


@router.get("/conversations/{lead_id}")
def conversation_detail(
    lead_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    state = db.scalar(select(SmsConversationState).where(
        SmsConversationState.organization_id == principal.organization_id,
        SmsConversationState.lead_id == lead_id,
    ))
    if not state:
        raise HTTPException(404, "Conversation state not found")
    return {
        "id": state.id,
        "lead_id": lead_id,
        "stage": state.stage,
        "status": state.status,
        "lead_temperature": state.lead_temperature,
        "opportunity_score": state.opportunity_score,
        "qualification": state.qualification,
        "agent_plan": state.agent_plan,
        "last_analysis": state.last_analysis,
        "transcript": _transcript(db, principal, lead_id),
        "updated_at": state.updated_at,
    }


@router.post("/conversations/{lead_id}/route-human")
def route_human(
    lead_id: int,
    payload: dict[str, Any] | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    state = _conversation(db, principal, lead_id)
    state.agent_plan = {
        **(state.agent_plan or {}),
        "requires_human": True,
        "escalation_reason": str((payload or {}).get("reason") or "manager_requested"),
        "next_action": "human_review",
    }
    create_task(
        db,
        "sms_human_handoff",
        {"conversation_state_id": state.id, "reason": state.agent_plan["escalation_reason"]},
        priority=100,
        lead_id=lead_id,
        requires_approval=False,
    )
    db.commit()
    return {"lead_id": lead_id, "routed": True, "agent_plan": state.agent_plan}


@router.get("/health")
def health():
    from .config import settings
    return {
        "status": "ok",
        "mode": "supervised_agentic",
        "primary_model_configured": bool(settings.anthropic_api_key),
        "fallback_model_configured": bool(settings.openai_api_key),
        "outbound_boundary": "draft_and_route_only",
        "required_execution_gates": ["sms_preflight", "compliance", "owner_approval", "outbound_gateway"],
    }

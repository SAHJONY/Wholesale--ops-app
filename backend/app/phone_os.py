from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead
from .voice_models import VoiceCall

router = APIRouter(prefix="/phone-os", tags=["phone operating system"])

MODEL = os.getenv("OPENAI_PHONE_QUALIFICATION_MODEL") or "gpt-5-mini"
HUMAN_TRANSFER = os.getenv("VOICE_HUMAN_TRANSFER_TARGET") or "+12816628581"
INBOUND_NUMBER = os.getenv("VOICE_INBOUND_NUMBER") or os.getenv("BLAND_INBOUND_NUMBER") or "+12164804413"
OUTBOUND_NUMBER = os.getenv("BLAND_DEFAULT_FROM_NUMBER") or "+13465214387"


def _linked(db: Session, principal: Principal, lead_id: int) -> None:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    if not linked:
        raise HTTPException(404, "Lead not found in this workspace")


def _status() -> dict[str, Any]:
    return {
        "provider": "bland",
        "inbound_number": INBOUND_NUMBER,
        "outbound_number": OUTBOUND_NUMBER,
        "human_transfer_target": HUMAN_TRANSFER,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "bland_configured": bool(os.getenv("BLAND_AI_API_KEY")),
        "qualification_model": MODEL,
        "operating_mode": "supervised_acquisition",
        "binding_offers_allowed": False,
        "contracts_autonomous": False,
        "money_movement_autonomous": False,
    }


@router.get("/status")
def status(principal: Principal = Depends(get_principal)):
    return {"organization_id": principal.organization_id, **_status()}


def _schema() -> dict[str, Any]:
    nullable_string = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    nullable_number = {"anyOf": [{"type": "number"}, {"type": "null"}]}
    nullable_int = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "motivation": nullable_string,
            "timeline_days": nullable_int,
            "condition": nullable_string,
            "seller_price": nullable_number,
            "property_address": nullable_string,
            "language": {"type": "string", "enum": ["en", "es", "other"]},
            "needs_human": {"type": "boolean"},
            "creative_finance_signal": {"type": "boolean"},
            "do_not_call": {"type": "boolean"},
            "summary": {"type": "string"},
            "evidence_quotes": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": [
            "motivation", "timeline_days", "condition", "seller_price", "property_address",
            "language", "needs_human", "creative_finance_signal", "do_not_call", "summary", "evidence_quotes",
        ],
    }


async def _extract(transcript: str) -> dict[str, Any]:
    key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise HTTPException(503, "OPENAI_API_KEY is not configured")
    prompt = (
        "Extract wholesale acquisition facts ONLY from the transcript. Do not infer or invent missing facts. "
        "Return null when motivation, timeline, condition, price, or address was not explicitly stated. "
        "Seller statements are claims, not verified property facts. Set needs_human true for a motivated seller, "
        "explicit request for a person, complex objection, legal/title issue, or creative-finance discussion. "
        "Set creative_finance_signal true only when terms, payments, taking over financing, seller finance, or a similar structure is explicitly discussed. "
        "Set do_not_call true if the person asks not to be contacted again.\n\nTRANSCRIPT:\n" + transcript[:24000]
    )
    body = {
        "model": MODEL,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "phone_qualification",
                "strict": True,
                "schema": _schema(),
            }
        },
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"OpenAI qualification failed ({response.status_code})")
    payload = response.json()
    text = str(payload.get("output_text") or "").strip()
    if not text:
        for item in payload.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    text += str(content.get("text") or "")
    try:
        data = json.loads(text)
    except Exception as exc:
        raise HTTPException(502, "OpenAI returned an invalid qualification payload") from exc
    data["openai_response_id"] = payload.get("id")
    return data


def _score(data: dict[str, Any]) -> dict[str, Any]:
    pillars = sum(1 for key in ("motivation", "timeline_days", "condition", "seller_price") if data.get(key) not in (None, ""))
    motivation = 0
    if data.get("motivation"):
        motivation += 35
    timeline = data.get("timeline_days")
    if isinstance(timeline, int):
        motivation += 30 if timeline <= 30 else 15 if timeline <= 90 else 5
    if data.get("seller_price") is not None:
        motivation += 20
    if data.get("condition"):
        motivation += 15
    motivation = min(100, motivation)
    hot = motivation >= 65 or bool(data.get("needs_human"))
    return {"pillars_captured": pillars, "motivation_score": motivation, "hot_lead": hot}


@router.post("/calls/{call_id}/qualify")
async def qualify_call(
    call_id: int,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    call = db.get(VoiceCall, call_id)
    if not call or call.organization_id != principal.organization_id:
        raise HTTPException(404, "Voice call not found")
    transcript = str(call.transcript_excerpt or "").strip()
    if not transcript:
        raise HTTPException(422, "Call has no transcript to qualify")
    if call.lead_id:
        _linked(db, principal, call.lead_id)

    extracted = await _extract(transcript)
    score = _score(extracted)
    evidence = dict(call.evidence or {})
    evidence["phone_qualification"] = {
        **extracted,
        **score,
        "facts_are_seller_stated": True,
        "verified_property_facts": False,
        "binding_offer_authority": False,
    }
    call.evidence = evidence

    if call.lead_id:
        lead = db.get(Lead, call.lead_id)
        if lead:
            lead.motivation_score = max(int(lead.motivation_score or 0), int(score["motivation_score"]))
            if extracted.get("timeline_days") is not None:
                lead.timeline_days = int(extracted["timeline_days"])
            if score["hot_lead"] and lead.status not in {"deleted", "closed"}:
                lead.status = "qualified"

    next_action = (
        "Transfer/escalate to human acquisitions and prepare source-backed underwriting."
        if score["hot_lead"] else
        "Keep in acquisition follow-up; verify owner/property facts before underwriting or outreach changes."
    )
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=call.lead_id,
        activity_type="phone_call_qualified",
        summary=f"Phone qualification completed: {score['pillars_captured']}/4 pillars, hot={score['hot_lead']}",
        metadata_json={"call_id": call.id, "qualification": extracted, "score": score, "next_action": next_action},
    ))
    db.commit()
    return {
        "call_id": call.id,
        "lead_id": call.lead_id,
        "qualification": extracted,
        "score": score,
        "next_action": next_action,
        "human_transfer_target": HUMAN_TRANSFER if score["hot_lead"] else None,
        "underwriting_ready": bool(score["hot_lead"] and call.lead_id),
        "verified_property_facts": False,
    }


@router.get("/calls")
def calls(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(VoiceCall).where(
        VoiceCall.organization_id == principal.organization_id
    ).order_by(VoiceCall.created_at.desc()).limit(100)).all()
    return [{
        "id": row.id,
        "lead_id": row.lead_id,
        "direction": row.direction,
        "contact": row.contact,
        "status": row.status,
        "outcome": row.outcome,
        "provider_call_id": row.provider_call_id,
        "ai_disclosed": row.ai_disclosed,
        "recorded": row.recorded,
        "verbal_opt_out": row.verbal_opt_out,
        "qualification": (row.evidence or {}).get("phone_qualification"),
        "created_at": row.created_at,
    } for row in rows]


@router.get("/outbound-template/{lead_id}")
def outbound_template(
    lead_id: int,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    _linked(db, principal, lead_id)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return {
        "lead_id": lead_id,
        "channel": "automated_call",
        "provider": "bland",
        "contact": lead.phone,
        "content": {
            "first_sentence": "Hi, this is the automated AI assistant for SAHJONY. Is now an okay time to speak briefly about the property?",
            "task": (
                "Qualify the seller using Motivation, Timeline, Condition, and Price. "
                "Treat seller statements as unverified claims. Do not promise an offer, contract, closing date, legal result, or payment. "
                "If the seller is motivated, asks for a person, discusses creative finance, title/legal issues, or wants to negotiate beyond information gathering, transfer to the human acquisitions target. "
                "If the seller asks not to be contacted, acknowledge it and end the call."
            ),
            "transfer_phone_number": HUMAN_TRANSFER,
            "from": OUTBOUND_NUMBER,
            "language": "en",
            "record": False,
            "summary_prompt": "Summarize Motivation, Timeline, Condition, Price, objections, requested follow-up, and whether human escalation is needed. Do not invent missing facts.",
        },
        "requires_compliance_decision": True,
        "requires_owner_approval": True,
        "dispatch_autonomous": False,
    }

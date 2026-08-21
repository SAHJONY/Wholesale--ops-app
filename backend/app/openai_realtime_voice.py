from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from openai import OpenAI

from .auth import Principal, get_principal

router = APIRouter(prefix="/openai-realtime-voice", tags=["OpenAI Realtime Voice"])

PROVIDER = "openai"
DEFAULT_MODEL = "gpt-realtime-2.1"
DEFAULT_VOICE = "cedar"


def _enabled(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _api_key() -> str:
    value = str(os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value:
        raise HTTPException(503, "OPENAI_API_KEY is not configured")
    return value


def _webhook_secret() -> str:
    value = str(os.getenv("OPENAI_WEBHOOK_SECRET") or "").strip()
    if not value:
        raise HTTPException(503, "OPENAI_WEBHOOK_SECRET is not configured")
    return value


def _model() -> str:
    return str(os.getenv("OPENAI_REALTIME_MODEL") or DEFAULT_MODEL).strip()


def _voice() -> str:
    return str(os.getenv("OPENAI_REALTIME_VOICE") or DEFAULT_VOICE).strip()


def _instructions() -> str:
    return (
        "You are the realtime automated acquisitions voice assistant for SAHJONY, a real-estate investment company. "
        "At the start of every call, clearly identify SAHJONY and disclose that you are an automated voice assistant. "
        "Speak naturally, briefly, and professionally. You may speak English or Spanish and should follow the caller's language. "
        "For seller conversations, capture only explicit Motivation, Timeline, Condition, and Price. "
        "Never invent ownership, title, liens, legal status, ARV, repairs, offers, contract terms, buyer interest, or consent. "
        "Never make a binding offer or promise a price. Never pressure the caller. "
        "If the caller asks not to be contacted, acknowledge the request and end the solicitation. "
        "If a caller asks for a human, or the conversation reaches legal, title, binding negotiation, or contract terms, transfer to a human. "
        "Do not record calls. SMS is disabled."
    )


async def _accept_call(call_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "realtime",
        "model": _model(),
        "instructions": _instructions(),
        "audio": {
            "output": {"voice": _voice()},
            "input": {
                "turn_detection": {
                    "type": "semantic_vad",
                    "create_response": True,
                    "interrupt_response": True,
                }
            },
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.openai.com/v1/realtime/calls/{call_id}/accept",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:1000]}
    if response.status_code >= 400:
        raise HTTPException(502, f"OpenAI Realtime rejected call accept: {payload.get('message') or response.status_code}")
    return payload


@router.get("/readiness")
def readiness(principal: Principal = Depends(get_principal)):
    configured = {
        "api_key": bool(str(os.getenv("OPENAI_API_KEY") or "").strip()),
        "webhook_secret": bool(str(os.getenv("OPENAI_WEBHOOK_SECRET") or "").strip()),
        "realtime_enabled": _enabled("OPENAI_REALTIME_VOICE_ENABLED", False),
        "sip_routing_enabled": _enabled("OPENAI_REALTIME_SIP_ENABLED", False),
        "model": _model(),
        "voice": _voice(),
        "sms_enabled": False,
        "call_recording": False,
    }
    return {
        "provider": PROVIDER,
        "engine": "native speech-to-speech realtime",
        "configured": configured,
        "ready": all((
            configured["api_key"],
            configured["webhook_secret"],
            configured["realtime_enabled"],
            configured["sip_routing_enabled"],
        )),
        "telephony_policy": {
            "carrier": "Bland remains the SAHJONY phone-number/call-routing provider until SIP handoff is production-proven",
            "conversation_engine": "OpenAI Realtime",
            "fallback": "Bland voice agent",
            "sms": "disabled",
            "recording": "disabled",
        },
    }


@router.post("/webhooks/openai")
async def openai_realtime_webhook(request: Request):
    raw = await request.body()
    try:
        client = OpenAI(api_key=_api_key(), webhook_secret=_webhook_secret())
        event = client.webhooks.unwrap(raw.decode("utf-8"), dict(request.headers))
    except Exception as exc:
        raise HTTPException(401, "Invalid OpenAI webhook signature") from exc

    event_type = getattr(event, "type", None)
    if event_type is None and isinstance(event, dict):
        event_type = event.get("type")
    if event_type != "realtime.call.incoming":
        return {"status": "ignored", "event_type": event_type}

    if not (_enabled("OPENAI_REALTIME_VOICE_ENABLED", False) and _enabled("OPENAI_REALTIME_SIP_ENABLED", False)):
        return {"status": "disabled", "accepted": False}

    data = getattr(event, "data", None)
    if data is None and isinstance(event, dict):
        data = event.get("data") or {}
    call_id = getattr(data, "call_id", None) if data is not None else None
    if not call_id and isinstance(data, dict):
        call_id = data.get("call_id")
    call_id = str(call_id or "").strip()
    if not call_id:
        raise HTTPException(422, "OpenAI realtime.call.incoming event missing call_id")

    await _accept_call(call_id)
    return {
        "status": "accepted",
        "call_id": call_id,
        "provider": PROVIDER,
        "model": _model(),
        "voice": _voice(),
        "recording": False,
        "sms_sent": 0,
    }

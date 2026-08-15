from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .agentic_voice_brain import (
    HUMAN_TRANSFER,
    REALTIME_MODEL,
    REALTIME_VOICE,
    execute_tool,
    realtime_tools,
    session_instructions,
)
from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .database import get_db
from .voice_intelligence import jurisdiction_policy, seller_memory

router = APIRouter(prefix="/agentic-voice/realtime", tags=["realtime voice orchestrator"])

OPENAI_BASE = "https://api.openai.com/v1"
CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,160}$")


def _api_key() -> str:
    key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise HTTPException(503, "OPENAI_API_KEY is not configured")
    return key


def _call_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not CALL_ID_RE.fullmatch(normalized):
        raise HTTPException(422, "Invalid Realtime call id")
    return normalized


def _parse_function_call_event(event: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if str(event.get("type") or "") != "response.function_call_arguments.done":
        raise HTTPException(422, "Unsupported Realtime event type")
    name = str(event.get("name") or "").strip()
    tool_call_id = str(event.get("call_id") or "").strip()
    raw_arguments = event.get("arguments")
    if not name or not tool_call_id or not isinstance(raw_arguments, str):
        raise HTTPException(422, "Malformed Realtime function-call event")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Realtime tool arguments are not valid JSON") from exc
    if not isinstance(arguments, dict):
        raise HTTPException(422, "Realtime tool arguments must be an object")
    return name, tool_call_id, arguments


def _client_events(tool_call_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": json.dumps(result, separators=(",", ":"), default=str),
            },
        },
        {"type": "response.create"},
    ]


def _session_config(
    db: Session,
    principal: Principal,
    lead_id: int | None = None,
) -> dict[str, Any]:
    instructions = session_instructions()
    context: dict[str, Any] | None = None
    if lead_id is not None:
        memory = seller_memory(db, principal, lead_id)
        state = (memory.get("property_context") or {}).get("state")
        policy = jurisdiction_policy(state, direction="inbound")
        context = {"memory": memory, "policy": policy}
        instructions += (
            "\n\nCURRENT LEAD CONTEXT (use as memory, not as permission to invent facts):\n"
            + json.dumps(context, default=str)[:12000]
        )
    return {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "voice": REALTIME_VOICE,
        "instructions": instructions,
        "tools": realtime_tools(),
        "tool_choice": "auto",
        "metadata": {
            "organization_id": str(principal.organization_id),
            "lead_id": str(lead_id) if lead_id is not None else "",
            "system": "sahjony_agentic_voice",
        },
    }


async def _openai_call_control(call_id: str, action: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    call_id = _call_id(call_id)
    if action not in {"accept", "refer", "hangup", "reject"}:
        raise HTTPException(422, "Unsupported Realtime call action")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{OPENAI_BASE}/realtime/calls/{call_id}/{action}",
            headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
            json=body if body is not None else {},
        )
    if response.status_code >= 400:
        detail = response.text[:1000]
        raise HTTPException(502, f"OpenAI Realtime {action} failed ({response.status_code}): {detail}")
    if not response.content:
        return {"ok": True}
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"ok": True, "result": payload}
    except ValueError:
        return {"ok": True, "response": response.text[:1000]}


@router.get("/session/{lead_id}")
def session_for_lead(
    lead_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    return {
        "session": _session_config(db, principal, lead_id),
        "execution_boundary": {
            "autonomous_conversation": True,
            "safe_tools": True,
            "binding_offer": False,
            "contract_execution": False,
            "money_movement": False,
            "autonomous_outbound_dispatch": False,
        },
    }


@router.post("/function-call-event")
def function_call_event(
    event: dict[str, Any],
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    name, tool_call_id, arguments = _parse_function_call_event(event)
    result = execute_tool(name, arguments, principal, db)
    lead_id_raw = arguments.get("lead_id")
    lead_id = int(lead_id_raw) if str(lead_id_raw or "").isdigit() else None
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        activity_type="voice_realtime_tool_executed",
        summary=f"Realtime voice tool executed: {name}",
        metadata_json={
            "tool_name": name,
            "tool_call_id": tool_call_id,
            "result_boundary": "tool output returned to OpenAI Realtime conversation",
        },
    ))
    db.commit()
    return {
        "tool_name": name,
        "tool_call_id": tool_call_id,
        "result": result,
        "client_events": _client_events(tool_call_id, result),
    }


@router.post("/calls/{call_id}/accept")
async def accept_call(
    call_id: str,
    payload: dict[str, Any] | None = None,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    lead_id_raw = (payload or {}).get("lead_id")
    lead_id = int(lead_id_raw) if str(lead_id_raw or "").isdigit() else None
    session = _session_config(db, principal, lead_id)
    result = await _openai_call_control(call_id, "accept", session)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        activity_type="voice_realtime_call_accepted",
        summary="OpenAI Realtime SIP call accepted into SAHJONY Agentic Voice",
        metadata_json={"call_id": call_id, "lead_id": lead_id},
    ))
    db.commit()
    return {"accepted": True, "call_id": call_id, "openai": result}


@router.post("/calls/{call_id}/transfer")
async def transfer_call(
    call_id: str,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    result = await _openai_call_control(call_id, "refer", {"target_uri": f"tel:{HUMAN_TRANSFER}"})
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="voice_realtime_call_transferred",
        summary="Realtime SIP call transferred to human acquisitions",
        metadata_json={"call_id": call_id, "target": HUMAN_TRANSFER},
    ))
    db.commit()
    return {"transferred": True, "call_id": call_id, "target": HUMAN_TRANSFER, "openai": result}


@router.post("/calls/{call_id}/hangup")
async def hangup_call(
    call_id: str,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    result = await _openai_call_control(call_id, "hangup")
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="voice_realtime_call_hung_up",
        summary="Realtime SIP call ended",
        metadata_json={"call_id": call_id},
    ))
    db.commit()
    return {"hung_up": True, "call_id": call_id, "openai": result}

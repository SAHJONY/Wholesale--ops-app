from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .config import settings
from .database import get_db
from .models import Buyer, Property
from .wholesale_skill_engine import SKILLS, _analysis

router = APIRouter(prefix="/openai-copilot", tags=["OpenAI wholesale copilot"])

SYSTEM_PROMPT = """You are SAHJONY Wholesale Copilot, an AI operating inside a supervised real-estate wholesale operating system.

Your job is to find, verify, analyze, prioritize, and explain residential wholesale opportunities nationwide using the tools available in this runtime.

Non-negotiable rules:
- Never invent owners, deeds, APNs, court records, liens, comparable sales, repair costs, buyer proof of funds, seller prices, or contact details.
- Separate verified facts, provider estimates, seller/listing claims, screening assumptions, and AI inference.
- Use web search for current external research when needed, but treat county/recorder/assessor/title evidence as higher authority for ownership and title facts.
- A lead without a verified seller/asking price is a prospect, not a confirmed $10K+ wholesale deal.
- The 70% rule is a screening heuristic only. It is not an appraisal, legal conclusion, lender decision, or authorization to offer.
- Do not represent title as clear unless a qualified title/closing source has verified it.
- Do not send offers, sign contracts, move money, publish mass outreach, or make legal/financial commitments. Those actions require explicit human approval through application gates.
- Prefer individual-owner single-family opportunities when the operator's stated buy box requires that filter.
- For material recommendations, identify the evidence used, important unknowns, and the next checkable action.

Available internal functions expose workspace facts and the source-grounded Deal Factory. Use them before assuming anything about properties already in SAHJONY.
"""

MAX_TOOL_ROUNDS = 6


def _linked_ids(db: Session, org_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == org_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _property_ids(db: Session, principal: Principal) -> list[int]:
    direct = set(_linked_ids(db, principal.organization_id, "property"))
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    if lead_ids:
        direct.update(db.scalars(select(Property.id).where(Property.lead_id.in_(lead_ids))).all())
    return sorted(direct)


def _buyers(db: Session, principal: Principal) -> list[Buyer]:
    ids = _linked_ids(db, principal.organization_id, "buyer")
    return list(db.scalars(select(Buyer).where(Buyer.id.in_(ids))).all()) if ids else []


def _buyer_dict(buyer: Buyer) -> dict[str, Any]:
    return {
        "id": buyer.id,
        "name": buyer.name,
        "company": buyer.company,
        "buyer_type": buyer.buyer_type,
        "zip_codes": buyer.zip_codes or [],
        "asset_types": buyer.asset_types or [],
        "min_price": buyer.min_price,
        "max_price": buyer.max_price,
        "max_rehab": buyer.max_rehab,
        "closing_days": buyer.closing_days,
        "proof_of_funds_verified": buyer.proof_of_funds_verified,
        "response_rate": buyer.response_rate,
        "reliability_score": buyer.reliability_score,
    }


def _candidate_rows(db: Session, principal: Principal, limit: int = 25) -> list[dict[str, Any]]:
    buyers = _buyers(db, principal)
    ids = _property_ids(db, principal)
    props = list(db.scalars(select(Property).where(Property.id.in_(ids))).all()) if ids else []
    rows = [_analysis(db, principal, prop, buyers) for prop in props]
    rows.sort(
        key=lambda row: (
            bool((row.get("decision") or {}).get("ready_for_promotion")),
            float((row.get("economics") or {}).get("projected_screening_spread") or -1e12),
            float((row.get("evidence") or {}).get("score") or 0),
        ),
        reverse=True,
    )
    return rows[: max(1, min(limit, 100))]


def _tool_schemas() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {"type": "web_search", "search_context_size": "medium"},
        {
            "type": "function",
            "name": "list_wholesale_skills",
            "description": "List the source-grounded wholesale skills and safety boundaries installed in SAHJONY.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "list_deal_factory_candidates",
            "description": "Return the highest-priority properties already inside the SAHJONY workspace, including owner/deed verification, economics, buyers, evidence gaps, and next action.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                "required": ["limit"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "analyze_workspace_property",
            "description": "Return the complete source-grounded Deal Factory analysis for one workspace property ID.",
            "parameters": {
                "type": "object",
                "properties": {"property_id": {"type": "integer", "minimum": 1}},
                "required": ["property_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "list_verified_buyers",
            "description": "Return workspace buyers and their buy boxes, including proof-of-funds verification and reliability fields. Does not contact buyers.",
            "parameters": {
                "type": "object",
                "properties": {"proof_of_funds_only": {"type": "boolean"}},
                "required": ["proof_of_funds_only"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]
    if settings.openai_vector_store_id:
        tools.insert(1, {"type": "file_search", "vector_store_ids": [settings.openai_vector_store_id]})
    return tools


def _execute_tool(name: str, arguments: dict[str, Any], db: Session, principal: Principal) -> Any:
    if name == "list_wholesale_skills":
        return {
            "skills": SKILLS,
            "policy": {
                "material_fact_traceability_target": 0.95,
                "invented_comps_allowed": False,
                "invented_owner_facts_allowed": False,
                "autonomous_legal_financial_commitments": False,
            },
        }
    if name == "list_deal_factory_candidates":
        return {"candidates": _candidate_rows(db, principal, int(arguments.get("limit") or 25))}
    if name == "analyze_workspace_property":
        property_id = int(arguments["property_id"])
        if property_id not in set(_property_ids(db, principal)):
            return {"error": "Property not found in this workspace", "property_id": property_id}
        prop = db.get(Property, property_id)
        if not prop:
            return {"error": "Property not found", "property_id": property_id}
        return _analysis(db, principal, prop, _buyers(db, principal))
    if name == "list_verified_buyers":
        rows = [_buyer_dict(b) for b in _buyers(db, principal)]
        if bool(arguments.get("proof_of_funds_only")):
            rows = [row for row in rows if row["proof_of_funds_verified"]]
        return {"buyers": rows, "count": len(rows)}
    return {"error": f"Unknown tool {name}"}


def _extract_sources(response: Any) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "web_search_call":
            continue
        action = getattr(item, "action", None)
        for source in getattr(action, "sources", []) or []:
            url = getattr(source, "url", None)
            if url and url not in seen:
                seen.add(url)
                sources.append({"type": "url", "url": url})
    return sources


def _run_agent(message: str, db: Session, principal: Principal) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise HTTPException(503, "OPENAI_API_KEY is not configured for the application")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    tools = _tool_schemas()
    response = client.responses.create(
        model=settings.openai_model,
        instructions=SYSTEM_PROMPT,
        input=message,
        tools=tools,
    )

    tool_trace: list[dict[str, Any]] = []
    for _round in range(MAX_TOOL_ROUNDS):
        calls = [item for item in (getattr(response, "output", []) or []) if getattr(item, "type", None) == "function_call"]
        if not calls:
            break
        outputs = []
        for call in calls:
            try:
                arguments = json.loads(call.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            result = _execute_tool(call.name, arguments, db, principal)
            tool_trace.append({"name": call.name, "arguments": arguments})
            outputs.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result, default=str),
            })
        response = client.responses.create(
            model=settings.openai_model,
            instructions=SYSTEM_PROMPT,
            previous_response_id=response.id,
            input=outputs,
            tools=tools,
        )
    else:
        raise HTTPException(502, "Copilot exceeded the bounded tool-call loop")

    return {
        "response_id": response.id,
        "model": getattr(response, "model", settings.openai_model),
        "answer": getattr(response, "output_text", "") or "",
        "tools_used": tool_trace,
        "web_sources": _extract_sources(response),
        "safety": {
            "research_and_analysis": True,
            "outbound_contact": False,
            "offer_submission": False,
            "contract_execution": False,
            "payments": False,
            "human_approval_required": True,
        },
    }


@router.get("/status")
def status(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "configured": bool(settings.openai_api_key),
        "model": settings.openai_model,
        "responses_api": True,
        "tools": {
            "web_search": True,
            "file_search": bool(settings.openai_vector_store_id),
            "workspace_functions": [
                "list_wholesale_skills",
                "list_deal_factory_candidates",
                "analyze_workspace_property",
                "list_verified_buyers",
            ],
            "computer_use": False,
            "realtime_voice": False,
        },
        "note": "ChatGPT web subscriptions are separate from API access; this runtime uses OPENAI_API_KEY.",
    }


@router.post("/chat")
def chat(
    payload: dict,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(422, "message is required")
    if len(message) > 20_000:
        raise HTTPException(422, "message is too long")

    result = _run_agent(message, db, principal)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="openai_wholesale_copilot",
        summary=f"Wholesale Copilot analysis: {message[:160]}",
        metadata_json={
            "response_id": result["response_id"],
            "model": result["model"],
            "tools_used": result["tools_used"],
            "web_source_count": len(result["web_sources"]),
        },
    ))
    db.commit()
    result["generated_at"] = datetime.now(timezone.utc)
    return result

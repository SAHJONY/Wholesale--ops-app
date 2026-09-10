from __future__ import annotations

import ipaddress
import os
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Property

router = APIRouter(prefix="/tinyfish", tags=["governed TinyFish property research"])

TINYFISH_RUN_URL = "https://agent.tinyfish.ai/v1/automation/run"
SOURCE_TYPES = {
    "assessor", "recorder", "tax", "court_docket", "code_enforcement", "auction", "permit",
}
SENSITIVE_QUERY_KEYS = {"access_token", "api_key", "apikey", "auth", "key", "signature", "token"}


class TinyFishResearchRequest(BaseModel):
    property_id: int = Field(gt=0)
    source_url: str = Field(min_length=12, max_length=2048)
    source_type: Literal[
        "assessor", "recorder", "tax", "court_docket", "code_enforcement", "auction", "permit"
    ]


def _allowed_domains() -> tuple[str, ...]:
    values = []
    for item in (os.getenv("TINYFISH_ALLOWED_DOMAINS") or "").split(","):
        domain = item.strip().lower().lstrip(".")
        if domain and domain not in values:
            values.append(domain)
    return tuple(values)


def _validate_source_url(source_url: str, allowed_domains: tuple[str, ...]) -> str:
    parsed = urlparse(source_url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise HTTPException(422, "TinyFish sources must be public HTTPS URLs without embedded credentials")
    if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise HTTPException(422, "TinyFish source URLs cannot contain credential-like query parameters")
    hostname = parsed.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise HTTPException(422, "IP-address TinyFish targets are not permitted")
    if not allowed_domains:
        raise HTTPException(503, "TinyFish source allowlist is not configured")
    if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains):
        raise HTTPException(422, "Source domain is not in TINYFISH_ALLOWED_DOMAINS")
    return parsed.geturl()


def _property_for_workspace(db: Session, principal: Principal, property_id: int) -> Property:
    explicit = db.scalar(select(WorkspaceEntity).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "property",
        WorkspaceEntity.entity_id == property_id,
    ))
    item = db.get(Property, property_id)
    inherited = False
    if item:
        inherited = db.scalar(select(WorkspaceEntity).where(
            WorkspaceEntity.organization_id == principal.organization_id,
            WorkspaceEntity.entity_type == "lead",
            WorkspaceEntity.entity_id == item.lead_id,
        )) is not None
    if not item or (explicit is None and not inherited):
        raise HTTPException(404, "Property not found in this workspace")
    if (item.state or "").strip().upper() == "TX":
        raise HTTPException(422, "Texas properties are excluded from the wholesale research workflow")
    return item


def _output_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "source_authority": {"type": "string", "nullable": True},
            "official_record_id": {"type": "string", "nullable": True},
            "property_address": {"type": "string", "nullable": True},
            "parcel_id": {"type": "string", "nullable": True},
            "owner_name": {"type": "string", "nullable": True},
            "event_type": {"type": "string", "nullable": True},
            "event_date": {"type": "string", "format": "date", "nullable": True},
            "record_status": {"type": "string", "nullable": True},
            "amount": {"type": "number", "minimum": 0, "nullable": True},
            "facts": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 12,
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 12,
            },
        },
        "required": ["facts", "warnings"],
    }


def _goal(item: Property, source_type: str) -> str:
    address = ", ".join(part for part in [item.address, item.city, item.state, item.zip_code] if part)
    privacy_rule = (
        "Do not collect phone numbers, email addresses, relatives, minors, allegations, or unrelated personal details. "
        if source_type == "court_docket"
        else "Do not collect phone numbers, email addresses, relatives, or unrelated personal details. "
    )
    return (
        f"Research only the official public {source_type.replace('_', ' ')} record for the single-family property "
        f"at {address}. Extract only facts visibly supported by this source. {privacy_rule}"
        "Do not infer ownership, legal status, distress, or identity when the page is incomplete. "
        "Return null for unsupported fields, list conflicts in warnings, and follow the output schema exactly."
    )


@router.get("/status")
def tinyfish_status(principal: Principal = Depends(get_principal)):
    domains = _allowed_domains()
    return {
        "provider": "tinyfish",
        "configured": bool(os.getenv("TINYFISH_API_KEY") and domains),
        "api_key_configured": bool(os.getenv("TINYFISH_API_KEY")),
        "allowed_domains": list(domains),
        "supported_source_types": sorted(SOURCE_TYPES),
        "mode": "preview_only",
        "organization_id": principal.organization_id,
        "governance": {
            "writes_property_truth": False,
            "contact_collection_allowed": False,
            "authoritative_verification_required": True,
            "human_review_required": True,
        },
    }


@router.post("/research")
async def research_property_source(
    payload: TinyFishResearchRequest,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    api_key = (os.getenv("TINYFISH_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(503, "TinyFish API key is not configured")
    source_url = _validate_source_url(payload.source_url, _allowed_domains())
    item = _property_for_workspace(db, principal, payload.property_id)
    started_at = datetime.now(timezone.utc)
    request_body = {
        "url": source_url,
        "goal": _goal(item, payload.source_type),
        "output_schema": _output_schema(),
    }
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False, trust_env=False) as client:
            response = await client.post(
                TINYFISH_RUN_URL,
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "TinyFish research timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "TinyFish research is currently unavailable") from exc

    if response.status_code == 401:
        raise HTTPException(503, "TinyFish credentials were rejected")
    if response.status_code == 402:
        raise HTTPException(503, "TinyFish wallet requires funding")
    if response.status_code == 429:
        raise HTTPException(429, "TinyFish rate limit reached")
    if response.status_code >= 400:
        raise HTTPException(502, f"TinyFish research failed with HTTP {response.status_code}")
    try:
        provider_payload = response.json()
    except ValueError as exc:
        raise HTTPException(502, "TinyFish returned an invalid response") from exc

    result = provider_payload.get("result") if isinstance(provider_payload, dict) else None
    if not isinstance(result, dict):
        result = provider_payload if isinstance(provider_payload, dict) else {}
    run_id = provider_payload.get("run_id") if isinstance(provider_payload, dict) else None
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=item.lead_id,
        activity_type="tinyfish_research_preview",
        summary=f"TinyFish preview completed for {payload.source_type}; property truth unchanged",
        metadata_json={
            "property_id": item.id,
            "source_domain": urlparse(source_url).hostname,
            "source_type": payload.source_type,
            "provider_run_id": run_id,
            "observed_at": started_at.isoformat(),
            "committed": False,
            "contact_data_requested": False,
        },
    ))
    db.commit()
    return {
        "provider": "tinyfish",
        "provider_run_id": run_id,
        "property_id": item.id,
        "source_url": source_url,
        "source_type": payload.source_type,
        "observed_at": started_at.isoformat(),
        "research_preview": result,
        "verification_state": "unverified_automation_preview",
        "committed": False,
        "contact_data_requested": False,
        "next_action": "Compare with an authoritative county record and approve before updating property truth.",
    }

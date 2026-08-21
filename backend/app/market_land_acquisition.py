from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .acquisition_intake import import_records
from .auth import Principal, require_role
from .database import get_db

router = APIRouter(prefix="/market-land-acquisition", tags=["market and land acquisition"])

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_RESULTS = 25
REQUEST_TIMEOUT_SECONDS = 60.0

MODES = {
    "on_market_sfr": {
        "label": "On-market motivated SFR",
        "property_type": "single_family",
        "default_source": "mls",
        "signals": ["on_market", "long_dom", "price_reduced", "needs_repairs", "as_is", "investor_special", "fsbo"],
        "prompt": "Find publicly accessible current residential listings that appear motivated or wholesale-compatible: long days on market (prefer 90+ DOM when supported), repeated price reductions, as-is, fixer-upper, handyman special, investor special, cash-only, estate sale, fire/water damage, or public FSBO. Prefer direct listing pages and public broker/MLS-syndication pages. Do not infer DOM, condition, seller motivation, or price changes unless the cited page supports them.",
    },
    "vacant_land": {
        "label": "Vacant lots / land",
        "property_type": "vacant_land",
        "default_source": "county",
        "signals": ["vacant_land", "vacant_lot", "land", "tax_delinquent_land", "owner_listed_land", "infill_lot"],
        "prompt": "Find publicly accessible vacant residential lots or land parcels that could fit an investor acquisition strategy. Prioritize county assessor/GIS/tax records, tax-sale/delinquency records, government open data, and public owner-listed/FSBO land listings. Prefer buildable/infill residential lots when the source explicitly supports the classification. Do not infer zoning, utilities, road access, buildability, wetlands, flood status, title, or market value without evidence.",
    },
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content") or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str):
                        parts.append(text)
    return "\n".join(parts).strip()


def _source_urls(payload: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            for source in action.get("sources") or []:
                if isinstance(source, dict) and isinstance(source.get("url"), str):
                    urls.add(source["url"].strip())
        if item.get("type") == "message":
            for content in item.get("content") or []:
                if isinstance(content, dict):
                    for annotation in content.get("annotations") or []:
                        if isinstance(annotation, dict) and isinstance(annotation.get("url"), str):
                            urls.add(annotation["url"].strip())
    return {url for url in urls if url.startswith("https://")}


def _schema(state: str, property_type: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["records"],
        "properties": {
            "records": {
                "type": "array",
                "maxItems": MAX_RESULTS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["address", "city", "state", "zip_code", "asking_price", "signals", "source_urls", "source_kind", "source_claim"],
                    "properties": {
                        "address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string", "enum": [state]},
                        "zip_code": {"type": "string"},
                        "asking_price": {"type": ["number", "null"]},
                        "signals": {"type": "array", "items": {"type": "string"}},
                        "source_urls": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                        "source_kind": {"type": "string", "enum": ["mls_public", "broker_listing", "fsbo_public", "county_assessor", "county_tax", "government_open_data", "tax_sale", "other_public"]},
                        "source_claim": {"type": "string"},
                    },
                },
            }
        },
    }


def _normalize_scope(payload: dict[str, Any]) -> tuple[str, str, str]:
    state = _clean(payload.get("state")).upper()
    city = _clean(payload.get("city"))
    county = _clean(payload.get("county"))
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise HTTPException(422, "state must be a two-letter US state code")
    if city and county:
        raise HTTPException(422, "Use either city or county, not both")
    return state, city, county


@router.get("/readiness")
def readiness(principal: Principal = Depends(require_role("acquisitions"))):
    configured = bool(_clean(os.getenv("OPENAI_API_KEY")))
    return {
        "configured": configured,
        "modes": [{"id": key, "label": value["label"], "property_type": value["property_type"]} for key, value in MODES.items()],
        "review_only": True,
        "outreach_allowed": False,
    }


@router.post("/run")
async def run_market_land_search(
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    mode = _clean(payload.get("mode"))
    config = MODES.get(mode)
    if not config:
        raise HTTPException(422, "mode must be on_market_sfr or vacant_land")
    api_key = _clean(os.getenv("OPENAI_API_KEY"))
    if not api_key:
        raise HTTPException(503, "OPENAI_API_KEY is not configured")
    state, city, county = _normalize_scope(payload)
    location = f"{city}, {state}" if city else (f"{county} County, {state}" if county else state)
    prompt = f"""
Search {location} for up to {MAX_RESULTS} {config['label']} opportunities.

{config['prompt']}

Requirements:
- Use only publicly accessible pages returned by web search.
- Every record must have a complete property address, city, state, ZIP, at least one source URL actually used, and a concise source-backed claim.
- Asking price may be null when the official public record does not provide one; never invent price.
- Do not return owner phone/email or skip-trace data.
- Do not infer ARV, repairs, zoning, title, seller motivation, or buildability.
- Return signals only when supported by the cited source.
""".strip()

    body = {
        "model": _clean(os.getenv("OPENAI_DISCOVERY_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"),
        "tools": [{"type": "web_search", "search_context_size": "high"}],
        "include": ["web_search_call.action.sources"],
        "input": prompt,
        "text": {"format": {"type": "json_schema", "name": "market_land_candidates", "strict": True, "schema": _schema(state, config["property_type"]) }},
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.post(OPENAI_RESPONSES_URL, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body)
        response.raise_for_status()
        raw = response.json()
    allowed_urls = _source_urls(raw)
    try:
        parsed = json.loads(_output_text(raw) or '{"records": []}')
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "Discovery provider returned invalid structured output") from exc

    records: list[dict[str, Any]] = []
    for item in parsed.get("records") or []:
        if not isinstance(item, dict):
            continue
        urls = [str(url).strip() for url in item.get("source_urls") or [] if str(url).strip() in allowed_urls]
        address, city_value, zip_code = _clean(item.get("address")), _clean(item.get("city")), _clean(item.get("zip_code"))
        if not address or not city_value or not zip_code or not urls:
            continue
        source_kind = _clean(item.get("source_kind"))
        source = "mls" if source_kind in {"mls_public", "broker_listing"} else ("fsbo" if source_kind == "fsbo_public" else "county")
        records.append({
            "address": address,
            "city": city_value,
            "state": state,
            "zip_code": zip_code,
            "source": source,
            "property_type": config["property_type"],
            "asking_price": item.get("asking_price"),
            "distress_signals": list(dict.fromkeys([_clean(v).lower().replace(" ", "_") for v in item.get("signals") or [] if _clean(v)] + [mode])),
            "external_id": urls[0],
            "source_urls": urls,
            "source_kind": source_kind,
            "source_claim": _clean(item.get("source_claim")),
            "provider_evidence": {"provider": "openai_web_search", "channel": mode, "source_urls": urls, "owner_verified": False, "contact_verified": False, "valuation_verified": False},
        })

    if not records:
        return {"status": "completed", "mode": mode, "location": location, "received": 0, "created": 0, "updated": 0, "duplicate": 0, "rejected": 0, "review_only": True, "outreach_allowed": False}

    result = import_records({"source": config["default_source"], "records": records, "_autonomous_review_only": True}, principal, db)
    return {"status": "completed", "mode": mode, "location": location, **result, "review_only": True, "outreach_allowed": False, "note": "On-market and vacant-land candidates remain evidence-gated before underwriting or outreach."}

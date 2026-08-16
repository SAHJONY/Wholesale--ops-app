from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .acquisition_intake import ALLOWED_SOURCES, import_records
from .auth import Principal

MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_RECORDS = 1000
REQUEST_TIMEOUT_SECONDS = 60.0
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PUBLIC_MARKETS_PER_RUN = 5
PUBLIC_RESULTS_PER_MARKET = 12

NATIONWIDE_STATE_ROTATION: tuple[tuple[str, str], ...] = (
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming"),
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_true(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in _TRUE_VALUES


def acquisition_feed_status() -> dict[str, Any]:
    url = str(os.getenv("AUTONOMOUS_PROPERTY_FEED_URL") or "").strip()
    parsed = urlparse(url)
    external_configured = bool(url)
    openai_configured = bool(str(os.getenv("OPENAI_API_KEY") or "").strip())
    provider_mode = "external_https" if external_configured else ("openai_web_public" if openai_configured else "unconfigured")
    configured = external_configured or openai_configured
    secure = parsed.scheme == "https" if external_configured else openai_configured
    auto_enabled = openai_configured and not external_configured
    enabled = _env_true("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION") or auto_enabled
    source = (
        str(os.getenv("AUTONOMOUS_PROPERTY_FEED_SOURCE") or "other").strip().lower()
        if external_configured
        else ("openai_web_public" if openai_configured else "other")
    )
    return {
        "enabled": enabled,
        "configured": configured,
        "secure": secure,
        "host": parsed.hostname if external_configured else ("api.openai.com" if openai_configured else None),
        "source": source,
        "provider_mode": provider_mode,
        "auto_configured": auto_enabled,
        "review_only": True,
        "outreach_allowed": False,
        "max_records_per_run": MAX_RECORDS,
        "markets_per_run": PUBLIC_MARKETS_PER_RUN if provider_mode == "openai_web_public" else None,
        "market_rotation": "50_state_public_record_rotation" if provider_mode == "openai_web_public" else None,
        "source_priority": [
            "county assessor/GIS/tax collector",
            "county recorder/clerk/deed index",
            "municipal code enforcement",
            "tax delinquency/tax sale notices",
            "sheriff/foreclosure/public notices",
            "government open-data portals/ArcGIS",
            "public FSBO pages as unverified listing claims",
        ] if provider_mode == "openai_web_public" else None,
    }


def _feed_config() -> dict[str, Any]:
    status = acquisition_feed_status()
    if not status["enabled"]:
        raise RuntimeError("Autonomous property acquisition is disabled")
    if not status["configured"]:
        raise RuntimeError("No authorized acquisition provider is configured")
    if not status["secure"]:
        raise RuntimeError("Autonomous property feed must use HTTPS")
    source = status["source"]
    if source not in ALLOWED_SOURCES:
        raise RuntimeError("AUTONOMOUS_PROPERTY_FEED_SOURCE is unsupported")

    if status["provider_mode"] == "openai_web_public":
        api_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
        return {
            "mode": "openai_web_public",
            "source": "openai_web_public",
            "url": OPENAI_RESPONSES_URL,
            "headers": {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            "model": str(os.getenv("OPENAI_DISCOVERY_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5").strip(),
        }

    headers = {"Accept": "application/json", "User-Agent": "sahjony-wholesale-os/1.0"}
    token = str(os.getenv("AUTONOMOUS_PROPERTY_FEED_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return {
        "mode": "external_https",
        "source": source,
        "url": str(os.environ["AUTONOMOUS_PROPERTY_FEED_URL"]).strip(),
        "headers": headers,
    }


def _extract_records(data: Any) -> list[dict[str, Any]]:
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise RuntimeError("Property feed response must be an array or an object containing records")
    if len(records) > MAX_RECORDS:
        raise RuntimeError(f"Property feed exceeds {MAX_RECORDS} records per run")
    return records


def _rotating_states(now: datetime | None = None) -> list[tuple[str, str]]:
    current = now or datetime.now(timezone.utc)
    start = (current.toordinal() * PUBLIC_MARKETS_PER_RUN) % len(NATIONWIDE_STATE_ROTATION)
    return [NATIONWIDE_STATE_ROTATION[(start + offset) % len(NATIONWIDE_STATE_ROTATION)] for offset in range(PUBLIC_MARKETS_PER_RUN)]


def _response_output_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _web_source_urls(payload: dict[str, Any]) -> set[str]:
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
                if not isinstance(content, dict):
                    continue
                for annotation in content.get("annotations") or []:
                    if isinstance(annotation, dict) and isinstance(annotation.get("url"), str):
                        urls.add(annotation["url"].strip())
    return {url for url in urls if url.startswith(("http://", "https://"))}


def _public_record_prompt(state_code: str, state_name: str) -> str:
    return f"""
Find up to {PUBLIC_RESULTS_PER_MARKET} current SINGLE-FAMILY distressed-property candidates in {state_name} ({state_code}) using publicly accessible web sources.

Priority sources:
1. Official county assessor, parcel/GIS, tax collector, treasurer.
2. Official recorder/clerk/deed indexes.
3. Municipal/county code enforcement, nuisance, unsafe-building, vacant-property records.
4. Official tax-delinquency/tax-sale lists.
5. Sheriff sale, foreclosure, pre-foreclosure or court/public-notice pages.
6. Government open-data and ArcGIS FeatureServer/MapServer pages.
7. Public FSBO pages only as unverified asking-price evidence.

Do not use private groups, login-gated sources, paid data brokers, skip-trace data, or inferred facts.
Every record MUST have a complete street address, city, state, ZIP and at least one URL that you actually used in web search.
Only include a property when the source explicitly supports at least one distress signal: tax delinquency/tax sale, code violation, vacant/unsafe/nuisance, foreclosure/sheriff/public sale, probate/estate wording, or public FSBO/owner-listed claim.
Do not return owner names, phones, emails, ARV, repair estimates or invented prices. Ownership is verified later from deed evidence.
""".strip()


def _discovery_schema(state_code: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["records"],
        "properties": {
            "records": {
                "type": "array",
                "maxItems": PUBLIC_RESULTS_PER_MARKET,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["address", "city", "state", "zip_code", "distress_signals", "source_urls", "source_kind", "source_claim"],
                    "properties": {
                        "address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string", "enum": [state_code]},
                        "zip_code": {"type": "string"},
                        "distress_signals": {"type": "array", "items": {"type": "string"}},
                        "source_urls": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                        "source_kind": {"type": "string", "enum": ["county_assessor", "county_tax", "recorder_deed", "code_enforcement", "tax_sale", "foreclosure_notice", "government_open_data", "fsbo_public", "other_public"]},
                        "source_claim": {"type": "string"},
                    },
                },
            },
        },
    }


def _normalize_web_record(raw: dict[str, Any], allowed_urls: set[str], state_code: str) -> dict[str, Any] | None:
    address = str(raw.get("address") or "").strip()
    city = str(raw.get("city") or "").strip()
    state = str(raw.get("state") or state_code).strip().upper()
    zip_code = str(raw.get("zip_code") or "").strip()
    signals = [str(value).strip().lower().replace(" ", "_") for value in (raw.get("distress_signals") or []) if str(value).strip()]
    urls = [str(value).strip() for value in (raw.get("source_urls") or []) if str(value).strip() in allowed_urls]
    if not all((address, city, state == state_code, zip_code, signals, urls)):
        return None
    return {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "source": "openai_web_public",
        "property_type": "single_family",
        "distress_signals": list(dict.fromkeys(signals)),
        "external_id": urls[0],
        "source_urls": urls,
        "source_kind": str(raw.get("source_kind") or "other_public"),
        "source_claim": str(raw.get("source_claim") or "").strip(),
        "provider_evidence": {
            "provider": "openai_web_search",
            "source_urls": urls,
            "owner_verified": False,
            "contact_verified": False,
            "arv_verified": False,
            "distress_source_backed": True,
        },
    }


async def _run_openai_public_discovery(client: httpx.AsyncClient, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for state_code, state_name in _rotating_states():
        body = {
            "model": config["model"],
            "tools": [{"type": "web_search", "search_context_size": "high"}],
            "include": ["web_search_call.action.sources"],
            "input": _public_record_prompt(state_code, state_name),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "distressed_property_candidates",
                    "strict": True,
                    "schema": _discovery_schema(state_code),
                }
            },
        }
        try:
            response = await client.post(config["url"], headers=config["headers"], json=body)
            response.raise_for_status()
            payload = response.json()
            allowed_urls = _web_source_urls(payload)
            output_text = _response_output_text(payload)
            parsed = json.loads(output_text) if output_text else {"records": []}
            for raw in parsed.get("records") or []:
                if isinstance(raw, dict):
                    normalized = _normalize_web_record(raw, allowed_urls, state_code)
                    if normalized is not None:
                        records.append(normalized)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"{state_code}:{type(exc).__name__}")
    return records[:MAX_RECORDS], warnings


async def run_autonomous_property_acquisition(
    db: Session,
    principal: Principal,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    config = _feed_config()
    source = str(config["source"])
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)
    warnings: list[str] = []
    try:
        if config["mode"] == "openai_web_public":
            records, warnings = await _run_openai_public_discovery(active_client, config)
        else:
            response = await active_client.get(config["url"], headers=config["headers"])
            response.raise_for_status()
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_FEED_BYTES or len(response.content) > MAX_FEED_BYTES:
                raise RuntimeError("Property feed response exceeds 5 MB")
            records = _extract_records(response.json())
    finally:
        if owns_client:
            await active_client.aclose()

    if not records:
        return {
            "status": "completed", "source": source, "received": 0,
            "created": 0, "updated": 0, "duplicate": 0, "rejected": 0,
            "review_only": True, "provider_warnings": warnings,
        }

    result = import_records(
        {
            "source": source,
            "records": records,
            "external_batch_id": f"autonomous-{datetime.now(timezone.utc).isoformat()}",
            "_autonomous_review_only": True,
        },
        principal,
        db,
    )
    return {
        "status": "completed",
        **result,
        "provider_mode": config["mode"],
        "provider_warnings": warnings,
        "review_only": True,
    }

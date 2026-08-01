from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class BatchDataConfig:
    api_key: str
    lookup_url: str
    environment: str

    @classmethod
    def from_env(cls) -> "BatchDataConfig | None":
        sandbox_key = (os.getenv("BATCHDATA_SANDBOX_API_KEY") or "").strip()
        production_key = (os.getenv("BATCHDATA_API_KEY") or "").strip()
        api_key = sandbox_key or production_key
        if not api_key:
            return None
        lookup_url = (os.getenv("BATCHDATA_PROPERTY_LOOKUP_URL") or "").strip()
        return cls(
            api_key=api_key,
            lookup_url=lookup_url,
            environment="sandbox" if sandbox_key else "production",
        )


class BatchDataProviderError(RuntimeError):
    def __init__(self, state: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.state = state
        self.http_status = http_status


def _classify(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ready_verified"
    if status_code in {401, 403}:
        return "invalid_credentials"
    if status_code == 402:
        return "payment_required"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "unavailable"
    return "configured_unverified"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "SAHJONY-Wholesale-OS/Provider-Intelligence-v3",
    }


def verify_credentials(config: BatchDataConfig) -> dict[str, Any]:
    if not config.lookup_url:
        return {
            "state": "configured_unverified",
            "verified": False,
            "environment": config.environment,
            "reason": "BATCHDATA_PROPERTY_LOOKUP_URL missing",
        }
    if not config.lookup_url.startswith("https://"):
        return {
            "state": "unavailable",
            "verified": False,
            "environment": config.environment,
            "reason": "BatchData lookup URL must use HTTPS",
        }
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            response = client.options(config.lookup_url, headers=_headers(config.api_key))
        state = _classify(response.status_code)
        return {
            "state": state,
            "verified": state == "ready_verified",
            "environment": config.environment,
            "http_status": response.status_code,
            "reason": None if state == "ready_verified" else state.replace("_", " "),
        }
    except httpx.TimeoutException:
        return {"state": "unavailable", "verified": False, "environment": config.environment, "reason": "verification timeout"}
    except httpx.HTTPError as exc:
        return {"state": "unavailable", "verified": False, "environment": config.environment, "reason": type(exc).__name__}


def lookup_property(config: BatchDataConfig, address: dict[str, str]) -> dict[str, Any]:
    if not config.lookup_url:
        raise BatchDataProviderError("configured_unverified", "BATCHDATA_PROPERTY_LOOKUP_URL missing")
    if not config.lookup_url.startswith("https://"):
        raise BatchDataProviderError("unavailable", "BatchData lookup URL must use HTTPS")

    payload = {
        "propertyAddress": {
            "street": address.get("street", ""),
            "city": address.get("city", ""),
            "state": address.get("state", ""),
            "zip": address.get("zip", ""),
        }
    }
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            response = client.post(config.lookup_url, headers=_headers(config.api_key), json=payload)
    except httpx.TimeoutException as exc:
        raise BatchDataProviderError("unavailable", "BatchData lookup timed out") from exc
    except httpx.HTTPError as exc:
        raise BatchDataProviderError("unavailable", type(exc).__name__) from exc

    state = _classify(response.status_code)
    if state != "ready_verified":
        raise BatchDataProviderError(state, f"BatchData lookup failed with HTTP {response.status_code}", response.status_code)

    try:
        raw = response.json()
    except ValueError as exc:
        raise BatchDataProviderError("unavailable", "BatchData returned unreadable JSON", response.status_code) from exc

    request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "provider_id": "batchdata",
        "environment": config.environment,
        "request_id": request_id,
        "observed_at": observed_at,
        "http_status": response.status_code,
        "raw": raw,
    }


def canonicalize_lookup(result: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("raw") or {}
    records = raw.get("results") or raw.get("data") or raw.get("result") or raw
    first = records[0] if isinstance(records, list) and records else records if isinstance(records, dict) else {}

    property_data = first.get("property") or first.get("propertyData") or first
    owner = first.get("owner") or first.get("ownerData") or {}
    valuation = first.get("valuation") or first.get("avm") or {}
    contacts = first.get("contacts") or first.get("contact") or {}
    mortgages = first.get("mortgages") or first.get("mortgage") or []
    liens = first.get("liens") or []
    comps = first.get("comparables") or first.get("comps") or []

    field_provenance = {
        field: {
            "provider_id": "batchdata",
            "observed_at": result.get("observed_at"),
            "request_id": result.get("request_id"),
            "environment": result.get("environment"),
            "confidence": 0.90,
        }
        for field in ("property", "owner", "valuation", "contacts", "mortgages", "liens", "comparables")
    }

    return {
        "property": property_data if isinstance(property_data, dict) else {},
        "owner": owner if isinstance(owner, dict) else {},
        "valuation": valuation if isinstance(valuation, dict) else {},
        "contacts": contacts if isinstance(contacts, (dict, list)) else {},
        "mortgages": mortgages if isinstance(mortgages, (dict, list)) else [],
        "liens": liens if isinstance(liens, (dict, list)) else [],
        "comparables": comps if isinstance(comps, list) else [],
        "field_provenance": field_provenance,
        "provider": {
            "id": "batchdata",
            "environment": result.get("environment"),
            "request_id": result.get("request_id"),
            "observed_at": result.get("observed_at"),
            "http_status": result.get("http_status"),
        },
        "truth_scope": ["licensed_property_data", "licensed_owner_data", "licensed_contact_data"],
        "confidence": 0.90,
        "limitations": [
            "Provider data must be independently reviewed before offers or outreach",
            "Contact data does not itself establish consent to call or text",
            "DNC and TCPA screening are required before communication",
        ],
    }

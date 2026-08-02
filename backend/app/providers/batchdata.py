from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_TOOL_NAME = "lookup_property"


@dataclass(frozen=True)
class BatchDataConfig:
    mcp_url: str
    api_token: str

    @classmethod
    def from_env(cls) -> "BatchDataConfig | None":
        mcp_url = (os.getenv("BATCHDATA_MCP_URL") or "").strip().rstrip("/")
        api_token = (os.getenv("BATCHDATA_API_TOKEN") or "").strip()
        if not mcp_url:
            return None
        return cls(mcp_url=mcp_url, api_token=api_token)


class BatchDataProviderError(RuntimeError):
    def __init__(self, state: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.state = state
        self.http_status = http_status


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _validate_config(config: BatchDataConfig) -> None:
    parsed = urlparse(config.mcp_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise BatchDataProviderError(
            "unavailable",
            "BATCHDATA_MCP_URL must be an HTTPS URL without embedded credentials",
        )
    if not config.api_token:
        raise BatchDataProviderError(
            "blocked",
            "BATCHDATA_API_TOKEN is not configured",
        )


def credential_status(config: BatchDataConfig | None) -> dict[str, Any]:
    missing: list[str] = []
    if config is None:
        missing.append("BATCHDATA_MCP_URL")
    elif not config.api_token:
        missing.append("BATCHDATA_API_TOKEN")
    return {
        "state": "ready" if not missing else "blocked",
        "configured": not missing,
        "verified": False,
        "missing": missing,
        "environment": "server_token_mcp",
        "reason": None if not missing else f"Missing {', '.join(missing)}",
    }


def _jsonrpc_response(response: httpx.Response, request_id: int) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise BatchDataProviderError(
            _classify(response.status_code),
            f"BatchData MCP failed with HTTP {response.status_code}",
            response.status_code,
        )
    content_type = response.headers.get("content-type", "").lower()
    candidates: list[dict[str, Any]] = []
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    item = json.loads(line[5:].strip())
                    if isinstance(item, dict):
                        candidates.append(item)
                except ValueError:
                    continue
    else:
        try:
            item = response.json()
            if isinstance(item, dict):
                candidates.append(item)
        except ValueError as exc:
            raise BatchDataProviderError("unavailable", "BatchData MCP returned unreadable data") from exc
    message = next((item for item in candidates if item.get("id") == request_id), None)
    if message is None:
        raise BatchDataProviderError(
            "unavailable",
            "BatchData MCP response did not contain the requested JSON-RPC result",
        )
    if message.get("error"):
        error = message["error"]
        raise BatchDataProviderError(
            "provider_error",
            str(error.get("message") if isinstance(error, dict) else error),
        )
    return message.get("result") or {}


def _mcp_exchange(
    config: BatchDataConfig,
    method: str,
    params: dict[str, Any] | None,
    request_id: int,
) -> tuple[dict[str, Any], str | None]:
    _validate_config(config)
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "SAHJONY-Wholesale-OS/Provider-Intelligence-v4",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sahjony-wholesale-ops", "version": "4.0"},
        },
    }
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            init_response = client.post(config.mcp_url, headers=headers, json=initialize)
            init_result = _jsonrpc_response(init_response, 1)
            protocol_version = str(init_result.get("protocolVersion") or MCP_PROTOCOL_VERSION)
            session_id = init_response.headers.get("mcp-session-id")
            headers["MCP-Protocol-Version"] = protocol_version
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            initialized = client.post(
                config.mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            if initialized.status_code < 200 or initialized.status_code >= 300:
                raise BatchDataProviderError(
                    _classify(initialized.status_code),
                    f"BatchData MCP initialization failed with HTTP {initialized.status_code}",
                    initialized.status_code,
                )
            response = client.post(
                config.mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
            )
            return _jsonrpc_response(response, request_id), session_id
    except httpx.HTTPError as exc:
        raise BatchDataProviderError("unavailable", f"BatchData MCP request failed: {exc}") from exc


def verify_credentials(config: BatchDataConfig, db: Session, organization_id: int) -> dict[str, Any]:
    del db, organization_id
    try:
        result, _ = _mcp_exchange(config, "tools/list", {}, 2)
        names = [tool.get("name") for tool in result.get("tools", []) if isinstance(tool, dict)]
        found = MCP_TOOL_NAME in names
        return {
            "state": "ready_verified" if found else "configured_unverified",
            "verified": found,
            "environment": "server_token_mcp",
            "tool": MCP_TOOL_NAME,
            "contacts_exposed": False,
            "data_committed": False,
            "external_actions": False,
            "reason": None if found else f"{MCP_TOOL_NAME} is not available for this account",
        }
    except BatchDataProviderError as exc:
        return {
            "state": exc.state,
            "verified": False,
            "environment": "server_token_mcp",
            "http_status": exc.http_status,
            "reason": str(exc),
        }


def lookup_property(
    config: BatchDataConfig,
    db: Session,
    organization_id: int,
    address: dict[str, str],
) -> dict[str, Any]:
    del db, organization_id
    if not all((address.get(field) or "").strip() for field in ("street", "city", "state", "zip")):
        raise BatchDataProviderError(
            "configured_unverified",
            "A complete street, city, state, and ZIP are required",
        )
    arguments = {
        "property_street": address["street"].strip(),
        "property_city": address["city"].strip(),
        "property_state": address["state"].strip(),
        "property_zip": address["zip"].strip(),
    }
    result, session_id = _mcp_exchange(
        config,
        "tools/call",
        {"name": MCP_TOOL_NAME, "arguments": arguments},
        2,
    )
    if result.get("isError"):
        raise BatchDataProviderError("provider_error", "BatchData lookup_property returned an error")
    raw: Any = result.get("structuredContent")
    if raw is None:
        texts = [
            item.get("text")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        raw_text = "\n".join(item for item in texts if isinstance(item, str))
        try:
            raw = json.loads(raw_text) if raw_text else result
        except ValueError:
            raw = {"text": raw_text}
    return {
        "provider_id": "batchdata",
        "environment": "server_token_mcp",
        "request_id": session_id,
        "observed_at": _now().isoformat(),
        "http_status": 200,
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
            "transport": "mcp_streamable_http",
            "tool": MCP_TOOL_NAME,
        },
        "truth_scope": ["licensed_property_data", "licensed_owner_data", "licensed_contact_data"],
        "confidence": 0.90,
        "limitations": [
            "Provider data must be independently reviewed before offers or outreach",
            "Contact data does not itself establish consent to call or text",
            "DNC and TCPA screening are required before communication",
        ],
    }

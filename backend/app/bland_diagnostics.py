from __future__ import annotations

import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from .auth import Principal, require_role

router = APIRouter(prefix="/internal/bland-diagnostics", tags=["Bland diagnostics"])

BLAND_API_BASE = "https://api.bland.ai/v1"
E164 = re.compile(r"^\+[1-9]\d{7,14}$")
EXPECTED_WEBHOOK = "https://www.sahjony.com/api/backend/bland-phone/webhooks/call"


def _clean_env(name: str) -> tuple[str, list[str]]:
    raw = str(os.getenv(name) or "")
    value = raw.strip()
    warnings: list[str] = []
    if raw != value:
        warnings.append("leading_or_trailing_whitespace")
    if len(value) >= 2 and value[0] in {'\"', "'", "“", "‘"} and value[-1] in {'\"', "'", "”", "’"}:
        warnings.append("wrapped_in_quotes")
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        warnings.append("bearer_prefix_present")
        value = value[7:].strip()
    return value, warnings


def _masked_number(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def _safe_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:300]}
    message = None
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if not message and isinstance(payload.get("errors"), list) and payload["errors"]:
            first = payload["errors"][0]
            message = first.get("error") if isinstance(first, dict) else str(first)
    return {
        "http_status": response.status_code,
        "ok": 200 <= response.status_code < 300,
        "provider_message": str(message)[:300] if message else None,
    }


async def _get(client: httpx.AsyncClient, path: str, api_key: str) -> tuple[httpx.Response, Any]:
    response = await client.get(
        f"{BLAND_API_BASE}{path}",
        headers={"authorization": api_key, "Accept": "application/json"},
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response, payload


@router.get("/run")
async def run_diagnostics(principal: Principal = Depends(require_role("manager"))):
    api_key, key_warnings = _clean_env("BLAND_AI_API_KEY")
    from_number, from_warnings = _clean_env("BLAND_DEFAULT_FROM_NUMBER")
    inbound_number, inbound_warnings = _clean_env("BLAND_INBOUND_NUMBER")
    webhook_url, webhook_warnings = _clean_env("BLAND_PHONE_WEBHOOK_URL")
    webhook_secret, secret_warnings = _clean_env("BLAND_AI_WEBHOOK_SECRET")
    org_id, org_warnings = _clean_env("BLAND_INBOUND_ORGANIZATION_ID")

    config = {
        "api_key_present": bool(api_key),
        "api_key_length": len(api_key) if api_key else 0,
        "api_key_format_warnings": key_warnings,
        "from_number": _masked_number(from_number),
        "from_number_valid_e164": bool(E164.match(from_number)) if from_number else False,
        "from_number_format_warnings": from_warnings,
        "inbound_number": _masked_number(inbound_number),
        "inbound_number_valid_e164": bool(E164.match(inbound_number)) if inbound_number else False,
        "inbound_number_format_warnings": inbound_warnings,
        "webhook_url_present": bool(webhook_url),
        "webhook_url_matches_expected": webhook_url == EXPECTED_WEBHOOK,
        "webhook_url_format_warnings": webhook_warnings,
        "webhook_signing_secret_present": bool(webhook_secret),
        "webhook_secret_format_warnings": secret_warnings,
        "organization_id_present": bool(org_id),
        "organization_id_format_warnings": org_warnings,
    }

    if not api_key:
        return {
            "status": "blocked",
            "root_cause": "missing_api_key",
            "config": config,
            "provider": None,
            "recommended_action": "Set BLAND_AI_API_KEY in the production environment and redeploy.",
            "secret_values_exposed": False,
            "call_placed": False,
        }

    async with httpx.AsyncClient(timeout=20) as client:
        me_response, me_payload = await _get(client, "/me", api_key)
        me_probe = _safe_response(me_response)

        if me_response.status_code in {401, 403}:
            return {
                "status": "failed",
                "root_cause": "provider_rejected_api_key",
                "config": config,
                "provider": {"me": me_probe},
                "recommended_action": (
                    "Generate or copy a fresh active API key from JUAN's Personal Org, replace only "
                    "BLAND_AI_API_KEY in Vercel, redeploy, and rerun this diagnostic."
                ),
                "secret_values_exposed": False,
                "call_placed": False,
            }

        if not me_probe["ok"]:
            return {
                "status": "failed",
                "root_cause": "bland_account_probe_failed",
                "config": config,
                "provider": {"me": me_probe},
                "recommended_action": "Review the Bland account/API status and retry after the provider error is resolved.",
                "secret_values_exposed": False,
                "call_placed": False,
            }

        memberships_response, memberships_payload = await _get(client, "/orgs/self/memberships", api_key)
        inbound_response, inbound_payload = await _get(client, "/inbound", api_key)
        outbound_response, outbound_payload = await _get(client, "/outbound", api_key)

    memberships: list[dict[str, Any]] = []
    if isinstance(memberships_payload, dict) and isinstance(memberships_payload.get("data"), list):
        memberships = [item for item in memberships_payload["data"] if isinstance(item, dict)]
    membership_ids = {str(item.get("org_id") or "") for item in memberships}
    membership_names = [str(item.get("org_display_name") or "") for item in memberships if item.get("org_display_name")]
    configured_org_match = org_id in membership_ids if org_id else False

    inbound_numbers = []
    if isinstance(inbound_payload, dict) and isinstance(inbound_payload.get("inbound_numbers"), list):
        inbound_numbers = inbound_payload["inbound_numbers"]
    outbound_numbers = []
    if isinstance(outbound_payload, dict) and isinstance(outbound_payload.get("outbound_numbers"), list):
        outbound_numbers = outbound_payload["outbound_numbers"]

    inbound_by_number = {
        str(item.get("phone_number") or ""): item
        for item in inbound_numbers
        if isinstance(item, dict)
    }
    outbound_set = {
        str(item.get("phone_number") or "")
        for item in outbound_numbers
        if isinstance(item, dict)
    }

    selected_inbound = inbound_by_number.get(inbound_number) if inbound_number else None
    checks = {
        "account_authenticated": True,
        "account_status_active": (
            str(me_payload.get("status") or "").lower() == "active"
            if isinstance(me_payload, dict)
            else False
        ),
        "configured_org_membership_match": configured_org_match,
        "configured_from_number_authorized_outbound": from_number in outbound_set if from_number else False,
        "configured_inbound_number_exists": inbound_number in inbound_by_number if inbound_number else False,
        "configured_inbound_webhook_matches": (
            str(selected_inbound.get("webhook") or "").strip() == EXPECTED_WEBHOOK
            if isinstance(selected_inbound, dict)
            else None
        ),
        "configured_inbound_recording_disabled": (
            selected_inbound.get("record") is False if isinstance(selected_inbound, dict) else None
        ),
    }

    failures = [name for name, passed in checks.items() if passed is False]
    if not configured_org_match and org_id and memberships:
        root_cause = "api_key_org_mismatch"
        action = (
            "The API key authenticates but BLAND_INBOUND_ORGANIZATION_ID is not one of the key's Bland memberships. "
            "Use the Organization ID from JUAN's Personal Org or generate a key while that organization is selected."
        )
    elif failures:
        root_cause = "configuration_mismatch"
        action = "Correct the failed checks and rerun diagnostics before placing another call."
    else:
        root_cause = None
        action = "Provider authentication and phone configuration are healthy; a controlled owner test call can be attempted next."

    return {
        "status": "healthy" if not failures else "degraded",
        "root_cause": root_cause,
        "config": config,
        "provider": {
            "me": me_probe,
            "memberships": _safe_response(memberships_response),
            "inbound": _safe_response(inbound_response),
            "outbound": _safe_response(outbound_response),
        },
        "checks": checks,
        "failed_checks": failures,
        "account": {
            "status": me_payload.get("status") if isinstance(me_payload, dict) else None,
            "balance_available": (
                (me_payload.get("billing") or {}).get("current_balance")
                if isinstance(me_payload, dict) and isinstance(me_payload.get("billing"), dict)
                else None
            ),
            "organization_memberships": membership_names,
            "configured_org_match": configured_org_match,
        },
        "inventory": {
            "inbound_numbers": [_masked_number(number) for number in inbound_by_number],
            "outbound_numbers": [_masked_number(number) for number in sorted(outbound_set)],
        },
        "recommended_action": action,
        "secret_values_exposed": False,
        "call_placed": False,
    }

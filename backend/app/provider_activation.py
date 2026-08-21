from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal, get_principal, require_role
from .batchdata_adapter import DEFAULT_BATCHDATA_SKIPTRACE_URL
from .integrations import PROVIDERS, _provider_status

router = APIRouter(prefix="/provider-activation", tags=["production provider activation"])

PROVIDER_GUIDANCE = {
    "attom": {
        "purpose": "Property, owner, deed, mortgage, AVM, foreclosure, and equity intelligence.",
        "environment": "production",
        "validation": "Credential presence plus a non-destructive property-detail request from the enrichment workflow.",
        "priority": 100,
    },
    "batchdata": {
        "purpose": "Seller phone and email enrichment with right-party and compliance review.",
        "environment": "production",
        "validation": "API-key readiness plus the official BatchData skip-trace endpoint (environment override supported); live contact lookup remains fail-closed.",
        "priority": 100,
    },
    "smarty": {
        "purpose": "Alternative property, owner, deed, assessment, tax, and parcel intelligence with rooftop geocoding.",
        "environment": "production",
        "validation": "Secret key pair presence; embedded keys cannot be used because requests originate from a public cloud provider.",
        "priority": 100,
    },
    "county_records": {
        "purpose": "Authoritative assessor, recorder, tax, deed, parcel, and legal-owner verification.",
        "environment": "public_or_manual",
        "validation": "Human-reviewed jurisdiction evidence before canonical ownership promotion.",
        "priority": 100,
    },
    "google_maps": {
        "purpose": "Optional geocoding and dated Street View support for visual condition review.",
        "environment": "optional",
        "validation": "Credential presence when enabled; imagery date and human review remain mandatory.",
        "priority": 40,
    },
    "fema": {
        "purpose": "Federal flood-zone and special-flood-hazard-area evidence.",
        "environment": "public",
        "validation": "Public-source availability with closing-stage insurance or survey confirmation.",
        "priority": 80,
    },
    "bland": {
        "purpose": "Approved inbound and outbound voice operations with outcome capture.",
        "environment": "production",
        "validation": "API key, signed webhook secret, and at least one Bland business/inbound number; no test call is placed by readiness checks.",
        "priority": 90,
    },
    "docuseal": {
        "purpose": "Owner-approved eSignature submissions and signed-document synchronization.",
        "environment": "production",
        "validation": "URL, API credential, and attorney-approved template readiness; no submission is created by readiness checks.",
        "priority": 90,
    },
    "docusign": {
        "purpose": "Optional fallback eSignature provider.",
        "environment": "optional",
        "validation": "Only required when selected as the active signature provider.",
        "priority": 20,
    },
    "object_storage": {
        "purpose": "Private encrypted retention for contracts, photos, proof of funds, and closing files.",
        "environment": "production",
        "validation": "Bucket and credential readiness; activation does not write an object.",
        "priority": 90,
    },
}

URL_ENV = {
    "batchdata": "BATCHDATA_SKIPTRACE_URL",
    "docuseal": "DOCUSEAL_URL",
}

DEFAULT_URLS = {
    "batchdata": DEFAULT_BATCHDATA_SKIPTRACE_URL,
}


def _safe_host_check(url_value: str) -> dict:
    parsed = urlparse(url_value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        return {"valid_url": False, "host_resolves": False, "error": "Invalid HTTP(S) URL"}
    try:
        socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        return {"valid_url": True, "host_resolves": True, "error": None}
    except Exception as exc:  # pragma: no cover - network dependent
        return {"valid_url": True, "host_resolves": False, "error": type(exc).__name__}


def _activation_item(provider: dict) -> dict:
    status = _provider_status(provider)
    guidance = PROVIDER_GUIDANCE.get(provider["id"], {})
    url_env = URL_ENV.get(provider["id"])
    url_value = (os.getenv(url_env) or "").strip() if url_env else ""
    if not url_value:
        url_value = DEFAULT_URLS.get(provider["id"], "")
    url_check = _safe_host_check(url_value) if url_value else None
    ready_states = {"configured", "available_public_or_manual"}
    selected_signature = str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower()
    blob_storage_ready = bool((os.getenv("BLOB_READ_WRITE_TOKEN") or "").strip())
    if provider["id"] == "object_storage" and blob_storage_ready:
        status = {
            **status,
            "state": "configured",
            "configured_variables": ["BLOB_READ_WRITE_TOKEN"],
            "missing_variables": [],
            "alternative_configured_variables": ["BLOB_READ_WRITE_TOKEN"],
        }
    required_now = provider.get("tier") in {"primary", "required", "authoritative_verification", "authoritative_public"}
    # ATTOM and Smarty are alternatives. Their shared requirement is scored once
    # in snapshot(), rather than incorrectly requiring ATTOM specifically.
    if provider["id"] in {"attom", "smarty"}:
        required_now = False
    if provider["id"] == "docusign":
        required_now = selected_signature == "docusign"
    if provider["id"] == "docuseal":
        required_now = selected_signature == "docuseal"
    activation_ready = status["state"] in ready_states and (not url_check or url_check["valid_url"])
    return {
        "id": provider["id"],
        "name": provider["name"],
        "category": provider["category"],
        "tier": provider["tier"],
        "state": status["state"],
        "required_now": required_now,
        "activation_ready": activation_ready,
        "configured_variables": status["configured_variables"],
        "missing_variables": status["missing_variables"],
        "optional_configured_variables": status["optional_configured_variables"],
        "alternative_configured_variables": status["alternative_configured_variables"],
        "capabilities": provider.get("capabilities", []),
        "purpose": guidance.get("purpose", "Production integration"),
        "environment": guidance.get("environment", "production"),
        "validation": guidance.get("validation", "Credential readiness review"),
        "priority": guidance.get("priority", 50),
        "url_check": url_check,
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal)):
    providers = sorted((_activation_item(item) for item in PROVIDERS), key=lambda item: (-item["priority"], item["name"]))
    property_ready = any(
        next((p["activation_ready"] for p in providers if p["id"] == pid), False)
        for pid in ["attom", "smarty"]
    )
    required = [item for item in providers if item["required_now"]]
    blockers = [item for item in required if not item["activation_ready"]]
    ready = [item for item in required if item["activation_ready"]]
    required_count = len(required) + 1  # one property-data slot: ATTOM OR Smarty
    ready_count = len(ready) + (1 if property_ready else 0)
    blocker_count = len(blockers) + (0 if property_ready else 1)
    score = round((ready_count / required_count) * 100) if required_count else 0
    selected_signature = str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower()
    blob_storage_ready = bool((os.getenv("BLOB_READ_WRITE_TOKEN") or "").strip())
    manual_contracts_ready = (
        selected_signature == "manual"
        and os.getenv("CONTRACT_EXECUTION_MODE") == "manual_governed"
        and blob_storage_ready
    )
    workflows = {
        "lead_acquisition": (
            property_ready
            and all(next((p["activation_ready"] for p in providers if p["id"] == pid), False) for pid in ["batchdata", "county_records"])
        ),
        "seller_outreach": next((p["activation_ready"] for p in providers if p["id"] == "bland"), False),
        "contract_execution": manual_contracts_ready or next((p["activation_ready"] for p in providers if p["id"] == ("docusign" if selected_signature == "docusign" else "docuseal")), False),
        "document_retention": next((p["activation_ready"] for p in providers if p["id"] == "object_storage"), False),
    }
    return {
        "generated_at": datetime.now(timezone.utc),
        "organization_id": principal.organization_id,
        "score": score,
        "status": "ready" if blocker_count == 0 else "blocked",
        "required_count": required_count,
        "ready_count": ready_count,
        "blocker_count": blocker_count,
        "property_data_requirement": {
            "mode": "any_of",
            "providers": ["attom", "smarty"],
            "ready": property_ready,
        },
        "selected_signature_provider": selected_signature,
        "workflows": workflows,
        "providers": providers,
        "safety": {
            "credentials_exposed": False,
            "external_messages_sent": False,
            "calls_placed": False,
            "sms_enabled": False,
            "signature_submissions_created": False,
            "storage_objects_written": False,
        },
    }


@router.post("/verify")
def verify(payload: dict | None = None, principal: Principal = Depends(require_role("manager"))):
    requested = str((payload or {}).get("provider_id") or "").strip()
    providers = [_activation_item(item) for item in PROVIDERS]
    if requested:
        item = next((provider for provider in providers if provider["id"] == requested), None)
        if not item:
            raise HTTPException(404, "Provider not found")
        return {"generated_at": datetime.now(timezone.utc), "organization_id": principal.organization_id, "provider": item, "safe_check_only": True}
    return {"generated_at": datetime.now(timezone.utc), "organization_id": principal.organization_id, "providers": providers, "safe_check_only": True}

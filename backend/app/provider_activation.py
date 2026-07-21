from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal, get_principal, require_role
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
        "validation": "Credential and endpoint format checks; live verification occurs through preview-only skip tracing.",
        "priority": 100,
    },
    "county_records": {
        "purpose": "Authoritative assessor, recorder, tax, deed, parcel, and legal-owner verification.",
        "environment": "public_or_manual",
        "validation": "Human-reviewed jurisdiction evidence before canonical ownership promotion.",
        "priority": 100,
    },
    "google_maps": {
        "purpose": "Geocoding and dated Street View support for visual condition review.",
        "environment": "production",
        "validation": "Credential presence; imagery date and human review remain mandatory.",
        "priority": 70,
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
        "validation": "Credential presence and webhook secret readiness; no test call is placed.",
        "priority": 90,
    },
    "twilio": {
        "purpose": "SMS, phone-number, delivery-status, and opt-out event infrastructure.",
        "environment": "production",
        "validation": "Credential and sender readiness; no message is sent by activation checks.",
        "priority": 90,
    },
    "docuseal": {
        "purpose": "Owner-approved eSignature submissions and signed-document synchronization.",
        "environment": "production",
        "validation": "URL, API credential, and attorney-approved template readiness; no submission is created.",
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
    url_check = None
    if url_env and (os.getenv(url_env) or "").strip():
        url_check = _safe_host_check(str(os.getenv(url_env)))
    ready_states = {"configured", "available_public_or_manual"}
    selected_signature = str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower()
    required_now = provider.get("tier") in {"primary", "required", "authoritative_verification", "authoritative_public"}
    if provider["id"] == "docusign":
        required_now = selected_signature == "docusign"
    if provider["id"] == "docuseal":
        required_now = selected_signature != "docusign"
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
    required = [item for item in providers if item["required_now"]]
    blockers = [item for item in required if not item["activation_ready"]]
    ready = [item for item in required if item["activation_ready"]]
    score = round((len(ready) / len(required)) * 100) if required else 0
    workflows = {
        "lead_acquisition": all(next((p["activation_ready"] for p in providers if p["id"] == pid), False) for pid in ["attom", "batchdata", "county_records"]),
        "seller_outreach": any(next((p["activation_ready"] for p in providers if p["id"] == pid), False) for pid in ["twilio", "bland"]),
        "contract_execution": next((p["activation_ready"] for p in providers if p["id"] == ("docusign" if str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower() == "docusign" else "docuseal")), False),
        "document_retention": next((p["activation_ready"] for p in providers if p["id"] == "object_storage"), False),
    }
    return {
        "generated_at": datetime.now(timezone.utc),
        "organization_id": principal.organization_id,
        "score": score,
        "status": "ready" if not blockers else "blocked",
        "required_count": len(required),
        "ready_count": len(ready),
        "blocker_count": len(blockers),
        "selected_signature_provider": str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower(),
        "workflows": workflows,
        "providers": providers,
        "safety": {
            "credentials_exposed": False,
            "external_messages_sent": False,
            "calls_placed": False,
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

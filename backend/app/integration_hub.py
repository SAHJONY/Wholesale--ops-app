from __future__ import annotations

import os
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .database import get_db
from .integration_hub_models import IntegrationHealthCheck, IntegrationOperationRun
from .integrations import PROVIDERS, _provider_status

router = APIRouter(prefix="/integration-hub", tags=["production integration operations"])

EXTRA_PROVIDERS = [
    {
        "id": "propstream", "name": "PropStream", "category": "lead_acquisition", "tier": "primary",
        "env": ["PROPSTREAM_API_KEY"], "optional_env": ["PROPSTREAM_BASE_URL"],
        "capabilities": ["lead_lists", "property_search", "distress_filters", "exports"],
        "authority": "licensed_property_data", "verification": "county_record_for_contract_critical_facts",
    },
    {
        "id": "hubspot", "name": "HubSpot CRM", "category": "crm", "tier": "primary",
        "env": ["HUBSPOT_ACCESS_TOKEN"], "optional_env": ["HUBSPOT_PORTAL_ID"],
        "capabilities": ["contacts", "companies", "deals", "activities", "webhooks"],
        "authority": "crm_sync", "verification": "workspace_mapping_and_deduplication",
    },
    {
        "id": "gmail", "name": "Gmail SMTP / API", "category": "email", "tier": "primary",
        "any_of_env": ["GMAIL_APP_PASSWORD", "GOOGLE_OAUTH_CLIENT_ID"],
        "optional_env": ["GMAIL_SMTP_USER", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"],
        "capabilities": ["transactional_email", "seller_email", "buyer_email"],
        "authority": "communications", "verification": "consent_opt_out_and_owner_approval",
    },
    {
        "id": "outlook", "name": "Microsoft Outlook / Graph", "category": "email", "tier": "optional",
        "env": ["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_TENANT_ID"],
        "capabilities": ["email", "calendar", "contacts"],
        "authority": "communications", "verification": "consent_opt_out_and_owner_approval",
    },
    {
        "id": "google_calendar", "name": "Google Calendar", "category": "scheduling", "tier": "primary",
        "any_of_env": ["GOOGLE_CALENDAR_REFRESH_TOKEN", "GOOGLE_SERVICE_ACCOUNT_JSON"],
        "optional_env": ["GOOGLE_CALENDAR_ID"],
        "capabilities": ["appointments", "closing_dates", "follow_up_events"],
        "authority": "scheduling", "verification": "workspace_calendar_mapping",
    },
    {
        "id": "stripe", "name": "Stripe", "category": "payments", "tier": "optional",
        "env": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
        "capabilities": ["billing", "payments", "webhooks"],
        "authority": "payment_processor", "verification": "webhook_signature_and_ledger_reconciliation",
    },
    {
        "id": "quickbooks", "name": "QuickBooks Online", "category": "accounting", "tier": "optional",
        "env": ["QUICKBOOKS_CLIENT_ID", "QUICKBOOKS_CLIENT_SECRET", "QUICKBOOKS_REALM_ID"],
        "optional_env": ["QUICKBOOKS_REFRESH_TOKEN"],
        "capabilities": ["expenses", "revenue", "invoices", "accounting_sync"],
        "authority": "accounting_system", "verification": "ledger_reconciliation",
    },
]

ALL_PROVIDERS = PROVIDERS + EXTRA_PROVIDERS
PROBE_URL_ENV = {
    "docuseal": "DOCUSEAL_URL",
    "propstream": "PROPSTREAM_BASE_URL",
    "batchdata": "BATCHDATA_SKIPTRACE_URL",
}


def _safe_probe(provider_id: str) -> tuple[str, int | None, str]:
    env_name = PROBE_URL_ENV.get(provider_id)
    if not env_name:
        return "not_probed", None, "Credential readiness evaluated; no non-destructive probe configured"
    url = str(os.getenv(env_name) or "").strip().rstrip("/")
    if not url:
        return "not_probed", None, f"{env_name} is not configured"
    started = time.monotonic()
    try:
        request = Request(url, method="HEAD", headers={"User-Agent": "SAHJONY-Integration-Health/1.0"})
        with urlopen(request, timeout=8) as response:
            latency = int((time.monotonic() - started) * 1000)
            code = int(getattr(response, "status", 200))
            return ("reachable" if code < 500 else "degraded"), latency, f"Endpoint returned HTTP {code}"
    except HTTPError as exc:
        latency = int((time.monotonic() - started) * 1000)
        if exc.code in {401, 403, 405}:
            return "reachable", latency, f"Endpoint reachable; HTTP {exc.code} requires authentication or disallows HEAD"
        return "degraded", latency, f"Endpoint returned HTTP {exc.code}"
    except (URLError, TimeoutError, ValueError) as exc:
        latency = int((time.monotonic() - started) * 1000)
        return "unreachable", latency, str(exc)


def _workflow_readiness(statuses: list[dict]) -> dict:
    by_id = {item["id"]: item for item in statuses}
    ready = lambda provider_id: by_id.get(provider_id, {}).get("state") in {"configured", "available_public_or_manual"}
    return {
        "lead_acquisition": ready("attom") and ready("batchdata"),
        "property_verification": ready("county_records"),
        "seller_outreach": ready("twilio") or ready("bland"),
        "email_delivery": ready("gmail") or ready("outlook"),
        "crm_sync": ready("hubspot"),
        "scheduling": ready("google_calendar"),
        "contract_execution": ready("docuseal") and ready("object_storage"),
        "accounting": ready("quickbooks"),
        "payments": ready("stripe"),
    }


def _latest_checks(db: Session, organization_id: int) -> dict[str, IntegrationHealthCheck]:
    rows = db.scalars(select(IntegrationHealthCheck).where(
        IntegrationHealthCheck.organization_id == organization_id
    ).order_by(IntegrationHealthCheck.checked_at.desc())).all()
    latest: dict[str, IntegrationHealthCheck] = {}
    for row in rows:
        latest.setdefault(row.provider_id, row)
    return latest


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    statuses = [_provider_status(provider) for provider in ALL_PROVIDERS]
    latest = _latest_checks(db, principal.organization_id)
    runs = db.scalars(select(IntegrationOperationRun).where(
        IntegrationOperationRun.organization_id == principal.organization_id
    ).order_by(IntegrationOperationRun.started_at.desc()).limit(20)).all()
    providers = []
    for item in statuses:
        check = latest.get(item["id"])
        providers.append({
            **item,
            "last_check": None if not check else {
                "status": check.status,
                "latency_ms": check.latency_ms,
                "message": check.message,
                "checked_at": check.checked_at,
            },
        })
    configured = sum(1 for item in statuses if item["state"] in {"configured", "available_public_or_manual"})
    return {
        "generated_at": datetime.utcnow(),
        "summary": {
            "providers": len(statuses),
            "configured": configured,
            "partial": sum(1 for item in statuses if item["state"] == "partial"),
            "not_configured": sum(1 for item in statuses if item["state"] == "not_configured"),
        },
        "workflow_readiness": _workflow_readiness(statuses),
        "providers": providers,
        "runs": [{
            "id": run.id, "trigger": run.trigger, "status": run.status,
            "providers_checked": run.providers_checked, "providers_ready": run.providers_ready,
            "providers_blocked": run.providers_blocked, "started_at": run.started_at,
            "completed_at": run.completed_at,
        } for run in runs],
    }


@router.post("/check")
def run_checks(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    requested = (payload or {}).get("provider_ids") or []
    provider_ids = {str(item) for item in requested if item}
    selected = [provider for provider in ALL_PROVIDERS if not provider_ids or provider["id"] in provider_ids]
    if not selected:
        raise HTTPException(422, "No supported providers selected")
    run = IntegrationOperationRun(organization_id=principal.organization_id, trigger=str((payload or {}).get("trigger") or "manual"))
    db.add(run)
    db.flush()
    results = []
    ready_count = 0
    for provider in selected:
        readiness = _provider_status(provider)
        probe_status, latency, message = _safe_probe(provider["id"])
        configured = readiness["state"] in {"configured", "available_public_or_manual"}
        status = "ready" if configured and probe_status not in {"unreachable", "degraded"} else "blocked" if not configured else "degraded"
        ready_count += int(status == "ready")
        row = IntegrationHealthCheck(
            organization_id=principal.organization_id,
            provider_id=provider["id"],
            status=status,
            readiness_state=readiness["state"],
            latency_ms=latency,
            message=message,
            details_json={
                "missing_variables": readiness["missing_variables"],
                "configured_variables": readiness["configured_variables"],
                "probe_status": probe_status,
            },
            checked_by_user_id=principal.user_id,
        )
        db.add(row)
        results.append({"provider_id": provider["id"], "status": status, "readiness_state": readiness["state"], "latency_ms": latency, "message": message})
    run.providers_checked = len(selected)
    run.providers_ready = ready_count
    run.providers_blocked = len(selected) - ready_count
    run.status = "completed"
    run.result_json = {"providers": results}
    run.completed_at = datetime.utcnow()
    db.commit()
    return {"run_id": run.id, "status": run.status, "providers_checked": run.providers_checked, "providers_ready": ready_count, "providers_blocked": run.providers_blocked, "results": results}


@router.get("/providers/{provider_id}")
def provider_detail(provider_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    provider = next((item for item in ALL_PROVIDERS if item["id"] == provider_id), None)
    if not provider:
        raise HTTPException(404, "Integration provider not found")
    history = db.scalars(select(IntegrationHealthCheck).where(
        IntegrationHealthCheck.organization_id == principal.organization_id,
        IntegrationHealthCheck.provider_id == provider_id,
    ).order_by(IntegrationHealthCheck.checked_at.desc()).limit(50)).all()
    return {
        "provider": _provider_status(provider),
        "history": [{
            "id": row.id, "status": row.status, "readiness_state": row.readiness_state,
            "latency_ms": row.latency_ms, "message": row.message, "details": row.details_json,
            "checked_at": row.checked_at,
        } for row in history],
    }

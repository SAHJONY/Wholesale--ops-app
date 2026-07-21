from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, Organization
from .database import get_db
from .integration_hub import ALL_PROVIDERS, _provider_status, _safe_probe
from .integration_hub_models import IntegrationHealthCheck, IntegrationOperationRun
from .integration_reliability_models import IntegrationReliabilityAlert, IntegrationReliabilityRun

router = APIRouter(prefix="/integration-reliability", tags=["integration reliability monitoring"])

WORKFLOW_DEPENDENCIES = {
    "attom": ["lead_acquisition", "property_intelligence"],
    "batchdata": ["lead_acquisition", "seller_contact_enrichment"],
    "propstream": ["lead_acquisition"],
    "county_records": ["property_verification"],
    "twilio": ["seller_outreach"],
    "bland": ["seller_outreach"],
    "gmail": ["email_delivery"],
    "outlook": ["email_delivery"],
    "hubspot": ["crm_sync"],
    "google_calendar": ["scheduling"],
    "docuseal": ["contract_execution"],
    "object_storage": ["contract_execution", "document_storage"],
    "stripe": ["payments"],
    "quickbooks": ["accounting"],
}


def _authorized_cron(authorization: str | None) -> None:
    configured = os.getenv("CRON_SECRET")
    if not configured:
        raise HTTPException(503, "CRON_SECRET is not configured")
    expected = f"Bearer {configured}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Invalid cron authorization")


def _check_provider(db: Session, organization_id: int, provider: dict, user_id: int | None = None) -> tuple[str, IntegrationHealthCheck]:
    readiness = _provider_status(provider)
    probe_status, latency, message = _safe_probe(provider["id"])
    configured = readiness["state"] in {"configured", "available_public_or_manual"}
    status = "ready" if configured and probe_status not in {"unreachable", "degraded"} else "blocked" if not configured else "degraded"
    row = IntegrationHealthCheck(
        organization_id=organization_id,
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
        checked_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    return status, row


def _update_alert(db: Session, organization_id: int, provider: dict, check: IntegrationHealthCheck) -> tuple[bool, bool]:
    alert = db.scalar(select(IntegrationReliabilityAlert).where(
        IntegrationReliabilityAlert.organization_id == organization_id,
        IntegrationReliabilityAlert.provider_id == provider["id"],
    ))
    opened = resolved = False
    if check.status == "ready":
        if alert and alert.status == "open":
            alert.status = "resolved"
            alert.failure_streak = 0
            alert.resolved_at = datetime.now(timezone.utc)
            alert.last_detected_at = datetime.now(timezone.utc)
            resolved = True
        return opened, resolved

    if not alert:
        alert = IntegrationReliabilityAlert(
            organization_id=organization_id,
            provider_id=provider["id"],
            status="open",
            failure_streak=1,
            severity="warning",
            affected_workflows=WORKFLOW_DEPENDENCIES.get(provider["id"], []),
            summary=f"{provider['name']} is {check.status}",
            details_json={"message": check.message, "readiness_state": check.readiness_state},
        )
        db.add(alert)
        opened = True
    else:
        if alert.status == "resolved":
            alert.status = "open"
            alert.first_detected_at = datetime.now(timezone.utc)
            alert.resolved_at = None
            alert.failure_streak = 1
            opened = True
        else:
            alert.failure_streak += 1
        alert.summary = f"{provider['name']} is {check.status}"
        alert.details_json = {"message": check.message, "readiness_state": check.readiness_state}
        alert.affected_workflows = WORKFLOW_DEPENDENCIES.get(provider["id"], [])
    alert.last_detected_at = datetime.now(timezone.utc)
    alert.severity = "critical" if alert.failure_streak >= 3 and provider.get("tier") in {"primary", "required"} else "warning"
    return opened, resolved


def _run_monitor(db: Session, trigger: str, organization_ids: list[int] | None = None, user_id: int | None = None) -> IntegrationReliabilityRun:
    run = IntegrationReliabilityRun(trigger=trigger)
    db.add(run)
    db.flush()
    organizations = db.scalars(select(Organization).where(Organization.is_active.is_(True))).all()
    if organization_ids:
        allowed = set(organization_ids)
        organizations = [item for item in organizations if item.id in allowed]
    opened = resolved = 0
    results = []
    for organization in organizations:
        op = IntegrationOperationRun(organization_id=organization.id, trigger=trigger)
        db.add(op)
        db.flush()
        ready = 0
        provider_results = []
        for provider in ALL_PROVIDERS:
            status, check = _check_provider(db, organization.id, provider, user_id)
            was_opened, was_resolved = _update_alert(db, organization.id, provider, check)
            opened += int(was_opened)
            resolved += int(was_resolved)
            ready += int(status == "ready")
            provider_results.append({"provider_id": provider["id"], "status": status})
        op.providers_checked = len(ALL_PROVIDERS)
        op.providers_ready = ready
        op.providers_blocked = len(ALL_PROVIDERS) - ready
        op.status = "completed"
        op.result_json = {"providers": provider_results}
        op.completed_at = datetime.now(timezone.utc)
        results.append({"organization_id": organization.id, "ready": ready, "blocked": op.providers_blocked})
    run.organizations_checked = len(organizations)
    run.alerts_opened = opened
    run.alerts_resolved = resolved
    run.status = "completed"
    run.result_json = {"organizations": results}
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    return run


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    alerts = db.scalars(select(IntegrationReliabilityAlert).where(
        IntegrationReliabilityAlert.organization_id == principal.organization_id,
    ).order_by(IntegrationReliabilityAlert.status, IntegrationReliabilityAlert.severity.desc(), IntegrationReliabilityAlert.last_detected_at.desc())).all()
    return {
        "summary": {
            "open": sum(1 for item in alerts if item.status == "open"),
            "critical": sum(1 for item in alerts if item.status == "open" and item.severity == "critical"),
            "resolved": sum(1 for item in alerts if item.status == "resolved"),
        },
        "alerts": [{
            "id": item.id,
            "provider_id": item.provider_id,
            "status": item.status,
            "severity": item.severity,
            "failure_streak": item.failure_streak,
            "affected_workflows": item.affected_workflows,
            "summary": item.summary,
            "details": item.details_json,
            "first_detected_at": item.first_detected_at,
            "last_detected_at": item.last_detected_at,
            "resolved_at": item.resolved_at,
        } for item in alerts],
    }


@router.post("/run-now")
def run_now(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    run = _run_monitor(db, "owner_manual", [principal.organization_id], principal.user_id)
    return {"run_id": run.id, "status": run.status, "alerts_opened": run.alerts_opened, "alerts_resolved": run.alerts_resolved}


@router.get("/scheduled")
def scheduled(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _authorized_cron(authorization)
    run = _run_monitor(db, "vercel_cron")
    return {"run_id": run.id, "status": run.status, "organizations_checked": run.organizations_checked, "alerts_opened": run.alerts_opened, "alerts_resolved": run.alerts_resolved}

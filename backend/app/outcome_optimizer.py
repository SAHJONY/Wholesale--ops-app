from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity, WorkspaceEntity
from .background_jobs import BackgroundJob
from .buyer_first_acquisition import refresh_buyer_box_matches
from .database import get_db
from .integration_reliability_models import IntegrationReliabilityRun
from .models import Buyer, Lead

router = APIRouter(prefix="/outcome-optimizer", tags=["outcome optimization"])

LOOKBACK_DAYS = 30


def _workspace_count(db: Session, organization_id: int, entity_type: str) -> int:
    return len(list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all()))


def _latest_reliability(db: Session) -> IntegrationReliabilityRun | None:
    return db.scalar(select(IntegrationReliabilityRun).where(
        IntegrationReliabilityRun.status == "completed",
    ).order_by(IntegrationReliabilityRun.completed_at.desc()))


def _recent_jobs(db: Session, organization_id: int, since: datetime) -> list[BackgroundJob]:
    return list(db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == organization_id,
        BackgroundJob.created_at >= since,
    ).order_by(BackgroundJob.created_at.desc()).limit(250)).all())


def _latest_job(jobs: list[BackgroundJob], job_type: str) -> BackgroundJob | None:
    return next((row for row in jobs if row.job_type == job_type), None)


def _pct(num: float, den: float) -> float:
    return round((num / den) * 100, 1) if den else 0.0


def _collector_health(job: BackgroundJob | None) -> dict[str, Any]:
    if not job:
        return {
            "status": "missing",
            "attempted": 0,
            "successful": 0,
            "records": 0,
            "success_rate_percent": 0.0,
            "warnings": [],
        }
    result = job.result_json or {}
    coverage = result.get("coverage") or {}
    catalog = coverage.get("collector_run_health") or {}
    attempted = sum(int((row or {}).get("attempted") or 0) for row in catalog.values())
    successful = sum(int((row or {}).get("successful") or 0) for row in catalog.values())
    records = sum(int((row or {}).get("records") or 0) for row in catalog.values())
    return {
        "status": job.status,
        "attempted": attempted,
        "successful": successful,
        "records": records,
        "success_rate_percent": _pct(successful, attempted),
        "warnings": list(result.get("provider_warnings") or [])[:50],
        "coverage_score": coverage.get("coverage_score"),
        "received": int(result.get("received") or 0),
        "created": int(result.get("created") or 0),
        "updated": int(result.get("updated") or 0),
        "rejected": int(result.get("rejected") or 0),
    }


def _priority(severity: str, impact: int, effort: int) -> float:
    severity_weight = {"critical": 1.0, "high": 0.85, "medium": 0.6, "low": 0.35}.get(severity, 0.5)
    return round(severity_weight * impact * (1.0 + (6 - max(1, min(5, effort))) / 10.0), 1)


def _recommendations(
    collector: dict[str, Any],
    providers_ready: int,
    providers_total: int,
    buyer_matches: dict[str, Any],
    lead_count: int,
    buyer_count: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    if collector["attempted"] and collector["success_rate_percent"] < 50:
        items.append({
            "id": "repair_public_collectors",
            "severity": "critical" if collector["success_rate_percent"] == 0 else "high",
            "impact": 100,
            "effort": 3,
            "problem": f"Public acquisition collectors succeed only {collector['success_rate_percent']}% of attempts.",
            "action": "Capture provider HTTP status/body class, separate auth/rate-limit/schema failures, then disable only failing collector-target pairs while healthy sources continue.",
            "success_metric": "collector success rate >= 80% and at least one source-backed candidate per active target set",
            "automatic_execution": False,
        })

    provider_rate = _pct(providers_ready, providers_total)
    if providers_total and provider_rate < 70:
        items.append({
            "id": "provider_readiness_recovery",
            "severity": "high",
            "impact": 90,
            "effort": 3,
            "problem": f"Only {providers_ready}/{providers_total} monitored providers are ready ({provider_rate}%).",
            "action": "Rank blocked integrations by workflow dependency and restore acquisition/property verification first, then communications, contracts and storage.",
            "success_metric": ">= 80% provider readiness with zero critical acquisition dependencies blocked",
            "automatic_execution": False,
        })

    pof_matches = int(buyer_matches.get("pof_verified_buyer_matches") or 0)
    match_count = len(buyer_matches.get("matches") or [])
    if match_count > 0 and pof_matches == 0:
        items.append({
            "id": "buyer_quality_upgrade",
            "severity": "high",
            "impact": 85,
            "effort": 2,
            "problem": f"There are {match_count} demand matches but no documentary POF-verified buyer matches.",
            "action": "Prioritize buyer records with documented proof of funds, explicit ZIP/asset box, rehab tolerance and closing speed; never infer POF.",
            "success_metric": ">= 10 POF-verified matches and >= 3 fast-track underwriting matches",
            "automatic_execution": False,
        })

    if lead_count == 0:
        items.append({
            "id": "restore_supply",
            "severity": "critical",
            "impact": 100,
            "effort": 2,
            "problem": "No workspace leads are available for the acquisition funnel.",
            "action": "Restore at least one authoritative county/public feed and verify imports before expanding geography.",
            "success_metric": ">= 20 source-backed leads entering review per operating day",
            "automatic_execution": False,
        })

    if buyer_count == 0:
        items.append({
            "id": "restore_buyer_demand",
            "severity": "high",
            "impact": 90,
            "effort": 2,
            "problem": "No workspace buyers are available for demand matching.",
            "action": "Load and verify buyer boxes before scaling seller acquisition.",
            "success_metric": ">= 10 active buyer profiles with explicit buying boxes",
            "automatic_execution": False,
        })

    for row in items:
        row["priority_score"] = _priority(row["severity"], int(row["impact"]), int(row["effort"]))
    items.sort(key=lambda row: row["priority_score"], reverse=True)
    return items


def build_outcome_snapshot(db: Session, principal: Principal) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=LOOKBACK_DAYS)
    jobs = _recent_jobs(db, principal.organization_id, since)
    acquisition_job = _latest_job(jobs, "autonomous_property_acquisition")
    collector = _collector_health(acquisition_job)

    reliability = _latest_reliability(db)
    providers_ready = 0
    providers_total = 0
    if reliability and isinstance(reliability.result_json, dict):
        organizations = reliability.result_json.get("organizations") or []
        org_row = next((row for row in organizations if int(row.get("organization_id") or 0) == principal.organization_id), None)
        if org_row:
            providers_ready = int(org_row.get("ready") or 0)
            providers_total = providers_ready + int(org_row.get("blocked") or 0)

    buyer_matches = refresh_buyer_box_matches(db, principal, limit=150, create_tasks=False)
    lead_count = _workspace_count(db, principal.organization_id, "lead")
    buyer_count = _workspace_count(db, principal.organization_id, "buyer")
    property_count = _workspace_count(db, principal.organization_id, "property")

    completed_jobs = sum(1 for row in jobs if row.status == "completed")
    failed_jobs = sum(1 for row in jobs if row.status in {"failed", "dead_letter"})
    retry_jobs = sum(1 for row in jobs if row.status == "retry")

    recommendations = _recommendations(
        collector,
        providers_ready,
        providers_total,
        buyer_matches,
        lead_count,
        buyer_count,
    )

    top_problem = recommendations[0] if recommendations else None
    return {
        "generated_at": now,
        "organization_id": principal.organization_id,
        "lookback_days": LOOKBACK_DAYS,
        "mode": "read_only_diagnostic",
        "execution_boundary": "no_outreach_no_offer_no_contract_no_secret_mutation_no_provider_purchase",
        "funnel": {
            "workspace_leads": lead_count,
            "workspace_properties": property_count,
            "workspace_buyers": buyer_count,
            "buyer_matches": len(buyer_matches.get("matches") or []),
            "pof_verified_buyer_matches": int(buyer_matches.get("pof_verified_buyer_matches") or 0),
            "fast_track_matches": int(buyer_matches.get("fast_track_count") or 0),
        },
        "acquisition_collectors": collector,
        "provider_reliability": {
            "ready": providers_ready,
            "total": providers_total,
            "ready_percent": _pct(providers_ready, providers_total),
            "latest_run_id": reliability.id if reliability else None,
            "latest_completed_at": reliability.completed_at if reliability else None,
        },
        "durable_jobs": {
            "observed": len(jobs),
            "completed": completed_jobs,
            "failed_or_dead_letter": failed_jobs,
            "retry": retry_jobs,
            "completion_rate_percent": _pct(completed_jobs, len(jobs)),
        },
        "top_bottleneck": top_problem,
        "recommended_actions": recommendations,
        "goal": "increase source-backed lead flow, verified buyer liquidity, and fast-track wholesale opportunities without weakening compliance or verification controls",
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return build_outcome_snapshot(db, principal)


@router.get("/plan")
def plan(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    data = build_outcome_snapshot(db, principal)
    return {
        "generated_at": data["generated_at"],
        "top_bottleneck": data["top_bottleneck"],
        "actions": data["recommended_actions"],
        "policy": "highest_expected_operational_impact_first; recommendations require owner-controlled implementation",
    }

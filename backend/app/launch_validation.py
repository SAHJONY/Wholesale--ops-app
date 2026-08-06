from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .background_jobs import BackgroundJob
from .database import get_db
from .models import Buyer, Deal, Lead, Property
from . import provider_requirements
from .property_data import property_data_configured

router = APIRouter(prefix="/launch-validation", tags=["production launch validation"])


def _result(name: str, passed: bool, severity: str, detail: str, remediation: str = "") -> dict:
    return {
        "name": name,
        "passed": passed,
        "severity": severity,
        "detail": detail,
        "remediation": remediation,
    }


def _workspace_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _provider_ready(*names: str, any_of: bool = False) -> bool:
    values = [bool((os.getenv(name) or "").strip()) for name in names]
    return any(values) if any_of else all(values)


def run_validation(db: Session, principal: Principal) -> dict:
    results: list[dict] = []
    database_ok = False
    migration_revision = None

    try:
        db.execute(text("SELECT 1"))
        database_ok = True
        tables = set(inspect(db.bind).get_table_names())
        if "alembic_version" in tables:
            migration_revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        results.append(_result("Database connectivity", True, "critical", "SELECT 1 completed successfully."))
    except Exception as exc:  # pragma: no cover - environment specific
        results.append(_result("Database connectivity", False, "critical", f"{type(exc).__name__}: {exc}", "Repair DATABASE_URL or database availability."))

    results.append(_result(
        "Migration baseline",
        bool(migration_revision),
        "critical",
        f"Revision: {migration_revision or 'not stamped'}",
        "Safely stamp the existing production schema after validating the complete database URI.",
    ))

    from api.index import app
    from .deployment_diagnostics import CRITICAL_ROUTES, registered_route_paths

    paths = registered_route_paths(app)
    missing_routes = [path for path in CRITICAL_ROUTES if path not in paths]
    results.append(_result(
        "Production route contract",
        not missing_routes,
        "critical",
        f"{len(CRITICAL_ROUTES) - len(missing_routes)}/{len(CRITICAL_ROUTES)} critical routes registered.",
        "Deploy the latest backend and resolve missing router imports.",
    ))

    lead_ids = _workspace_ids(db, principal.organization_id, "lead") if database_ok else []
    property_ids = _workspace_ids(db, principal.organization_id, "property") if database_ok else []
    buyer_ids = _workspace_ids(db, principal.organization_id, "buyer") if database_ok else []
    deal_ids = _workspace_ids(db, principal.organization_id, "deal") if database_ok else []

    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all() if lead_ids else []
    properties = db.scalars(select(Property).where(Property.id.in_(property_ids))).all() if property_ids else []
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all() if deal_ids else []

    orphan_properties = [p.id for p in properties if p.lead_id not in set(lead_ids)]
    property_id_set = set(property_ids)
    orphan_deals = [d.id for d in deals if d.property_id not in property_id_set]
    texas_properties = [p.id for p in properties if (p.state or "").upper() == "TX"]

    results.extend([
        _result("Workspace entity integrity", not orphan_properties and not orphan_deals, "critical", f"Orphan properties: {len(orphan_properties)}; orphan deals: {len(orphan_deals)}.", "Repair tenant links before launch."),
        _result("Texas exclusion", not texas_properties, "critical", f"Texas properties in active workspace: {len(texas_properties)}.", "Remove or suppress Texas records from wholesale workflows."),
        _result("Lead inventory", bool(leads), "medium", f"Tenant-linked leads: {len(leads)}.", "Import verified production leads."),
        _result("Buyer inventory", bool(buyers), "medium", f"Tenant-linked buyers: {len(buyers)}.", "Import verified buyers and buying boxes."),
        _result("Deal workflow evidence", bool(deals), "medium", f"Tenant-linked deals: {len(deals)}.", "Run one controlled lead-to-closing rehearsal."),
    ])

    ready_properties = [p for p in properties if p.arv is not None and p.repairs is not None and p.mao is not None]
    verified_buyers = [b for b in buyers if b.proof_of_funds_verified]
    results.extend([
        _result("Underwriting evidence", bool(ready_properties), "high", f"Properties with ARV, repairs, and MAO: {len(ready_properties)}.", "Complete verified underwriting for at least one property."),
        _result("Buyer proof of funds", bool(verified_buyers), "high", f"POF-verified buyers: {len(verified_buyers)}.", "Verify proof of funds before disposition."),
    ])

    # Same registry go-live reads, so the two screens cannot answer this
    # question differently. They used to: this file required both Twilio
    # variables together while go-live took any one of them.
    results.append(_result(
        "Provider: property data",
        property_data_configured(),
        "critical",
        "ATTOM or Smarty credentials present." if property_data_configured() else "Neither ATTOM nor a complete Smarty pair is configured.",
        "Configure ATTOM_API_KEY, or SMARTY_AUTH_ID and SMARTY_AUTH_TOKEN together.",
    ))
    for item in provider_requirements.evaluate_all():
        results.append(_result(
            f"Provider: {item['label'].lower()}",
            item["ready"],
            item["severity"],
            "Configured." if item["ready"] else f"Missing: {', '.join(item['missing'])}.",
            item["remediation"] or "Configure and health-check the production provider.",
        ))

    dead_letters = 0
    stale_running = 0
    if database_ok:
        dead_letters = int(db.scalar(select(func.count(BackgroundJob.id)).where(
            BackgroundJob.organization_id == principal.organization_id,
            BackgroundJob.status == "dead_letter",
        )) or 0)
        stale_running = int(db.scalar(select(func.count(BackgroundJob.id)).where(
            BackgroundJob.organization_id == principal.organization_id,
            BackgroundJob.status == "running",
        )) or 0)
    results.extend([
        _result("No dead-letter jobs", dead_letters == 0, "high", f"Dead-letter jobs: {dead_letters}.", "Resolve or retry exhausted jobs."),
        _result("No active stuck jobs", stale_running == 0, "medium", f"Currently running jobs: {stale_running}.", "Allow the recovery worker to reclaim stale leases."),
    ])

    weights = {"critical": 10, "high": 6, "medium": 3, "low": 1}
    possible = sum(weights[item["severity"]] for item in results)
    earned = sum(weights[item["severity"]] for item in results if item["passed"])
    score = round(earned / possible * 100) if possible else 0
    critical_failures = [item for item in results if not item["passed"] and item["severity"] == "critical"]
    high_failures = [item for item in results if not item["passed"] and item["severity"] == "high"]
    status = "ready" if not critical_failures and not high_failures and score >= 85 else "conditional" if not critical_failures and score >= 65 else "blocked"

    return {
        "generated_at": datetime.now(timezone.utc),
        "status": status,
        "score": score,
        "summary": {
            "passed": len([item for item in results if item["passed"]]),
            "failed": len([item for item in results if not item["passed"]]),
            "critical_failures": len(critical_failures),
            "high_failures": len(high_failures),
        },
        "results": results,
        "missing_routes": missing_routes,
        "provider_checks": provider_checks,
        "workspace": {
            "leads": len(leads),
            "properties": len(properties),
            "buyers": len(buyers),
            "deals": len(deals),
            "underwritten_properties": len(ready_properties),
            "verified_buyers": len(verified_buyers),
        },
        "safety": {
            "non_destructive": True,
            "outbound_messages_sent": False,
            "contracts_sent": False,
            "payments_created": False,
        },
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    latest = db.scalar(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.activity_type == "launch_validation",
    ).order_by(CrmActivity.created_at.desc()))
    return {
        "latest_report": latest.metadata_json if latest else None,
        "latest_run_at": latest.created_at if latest else None,
    }


@router.post("/run")
def run(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    report = run_validation(db, principal)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="launch_validation",
        summary=f"Launch validation completed with status {report['status']} and score {report['score']}",
        metadata_json=report,
    ))
    db.commit()
    return report

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import CrmActivity, WorkspaceEntity
from .background_jobs import BackgroundJob
from .database import get_db
from .models import Buyer, Deal, Lead, Property

router = APIRouter(prefix="/go-live", tags=["production go-live command"])

PROVIDER_GROUPS = {
    "property_data": ["ATTOM_API_KEY", "PROPSTREAM_API_KEY"],
    "property_intelligence_mcp": ["BATCHDATA_MCP_URL", "BATCHDATA_API_TOKEN"],
    "contact_enrichment": ["BATCHDATA_SKIPTRACE_URL", "BATCHDATA_API_KEY"],
    "communications": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "BLAND_AI_API_KEY"],
    "contracts": ["DOCUSEAL_URL", "DOCUSEAL_API_KEY"],
    "email": ["SMTP_USER", "SMTP_PASS"],
    "storage": ["S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"],
}

OWNER_PAGES = [
    "/owner", "/owner/attention", "/owner/integrations", "/owner/system-health",
    "/owner/security", "/owner/sessions", "/owner/continuity", "/owner/jobs",
    "/owner/audit", "/owner/national-intelligence", "/owner/contracts",
]


def _configured(names: list[str], require_all: bool = True) -> bool:
    states = [bool((os.getenv(name) or "").strip()) for name in names]
    return all(states) if require_all else any(states)


def _workspace_count(db: Session, organization_id: int, entity_type: str) -> int:
    return int(db.scalar(select(func.count(WorkspaceEntity.id)).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )) or 0)


def _check(name: str, category: str, ready: bool, severity: str, detail: str, action: str) -> dict:
    return {
        "name": name,
        "category": category,
        "ready": ready,
        "severity": severity,
        "detail": detail,
        "action": action,
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    database_ok = False
    migration_version = None
    database_error = None
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
        tables = set(inspect(db.bind).get_table_names())
        if "alembic_version" in tables:
            migration_version = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - environment-specific
        database_error = f"{type(exc).__name__}: {exc}"

    from api.index import app
    from .deployment_diagnostics import CRITICAL_ROUTES, registered_route_paths

    paths = registered_route_paths(app)
    missing_routes = [path for path in CRITICAL_ROUTES if path not in paths]

    lead_count = _workspace_count(db, principal.organization_id, "lead") if database_ok else 0
    property_count = _workspace_count(db, principal.organization_id, "property") if database_ok else 0
    deal_count = _workspace_count(db, principal.organization_id, "deal") if database_ok else 0
    buyer_count = _workspace_count(db, principal.organization_id, "buyer") if database_ok else 0

    jobs = {}
    if database_ok:
        jobs = dict(db.execute(select(BackgroundJob.status, func.count(BackgroundJob.id)).where(
            BackgroundJob.organization_id == principal.organization_id,
        ).group_by(BackgroundJob.status)).all())

    providers = {
        "property_data": _configured(PROVIDER_GROUPS["property_data"], require_all=False),
        "property_intelligence_mcp": _configured(PROVIDER_GROUPS["property_intelligence_mcp"]),
        "contact_enrichment": _configured(PROVIDER_GROUPS["contact_enrichment"]),
        "communications": _configured(PROVIDER_GROUPS["communications"], require_all=False),
        "contracts": _configured(PROVIDER_GROUPS["contracts"]),
        "email": _configured(PROVIDER_GROUPS["email"]),
        "storage": _configured(PROVIDER_GROUPS["storage"]),
    }

    checks = [
        _check("Database connectivity", "infrastructure", database_ok, "critical", database_error or "Database responds to SELECT 1.", "Repair DATABASE_URL or database availability."),
        _check("Migration baseline", "infrastructure", bool(migration_version), "critical", f"Revision: {migration_version or 'not stamped'}", "Safely establish the Alembic production baseline."),
        _check("Critical API contract", "deployment", not missing_routes, "critical", f"{len(CRITICAL_ROUTES) - len(missing_routes)}/{len(CRITICAL_ROUTES)} routes registered.", "Deploy latest backend and resolve missing routes."),
        _check("Property data provider", "integrations", providers["property_data"], "critical", "ATTOM or PropStream credential readiness.", "Connect a licensed property-data provider."),
        _check("Provider Intelligence MCP", "integrations", providers["property_intelligence_mcp"], "critical", "BatchData MCP transport URL and server-token readiness.", "Configure BATCHDATA_MCP_URL and BATCHDATA_API_TOKEN."),
        _check("Contact enrichment", "integrations", providers["contact_enrichment"], "critical", "BatchData REST skip-trace endpoint and API-key readiness.", "Configure BATCHDATA_SKIPTRACE_URL and BATCHDATA_API_KEY."),
        _check("Seller communications", "integrations", providers["communications"], "critical", "Twilio or Bland AI credential readiness.", "Connect an approved communications provider."),
        _check("Contract execution", "integrations", providers["contracts"], "high", "DocuSeal URL and API credential readiness.", "Configure DocuSeal production credentials."),
        _check("Transactional email", "integrations", providers["email"], "high", "SMTP credential readiness.", "Configure production email delivery."),
        _check("Offsite document storage", "continuity", providers["storage"], "high", "S3-compatible storage readiness.", "Configure encrypted offsite storage."),
        _check("No dead-letter jobs", "automation", int(jobs.get("dead_letter", 0)) == 0, "high", f"Dead-letter jobs: {int(jobs.get('dead_letter', 0))}", "Review and retry or resolve dead-letter jobs."),
        _check("Lead data present", "business", lead_count > 0, "medium", f"Workspace leads: {lead_count}", "Import or create production leads."),
        _check("Buyer network present", "business", buyer_count > 0, "medium", f"Workspace buyers: {buyer_count}", "Import verified cash buyers and buying boxes."),
        _check("Deal workflow exercised", "business", deal_count > 0, "medium", f"Workspace deals: {deal_count}", "Run one controlled lead-to-closing test deal."),
    ]

    weights = {"critical": 10, "high": 6, "medium": 3, "low": 1}
    possible = sum(weights[item["severity"]] for item in checks)
    earned = sum(weights[item["severity"]] for item in checks if item["ready"])
    score = round((earned / possible) * 100) if possible else 0
    blockers = [item for item in checks if not item["ready"] and item["severity"] in {"critical", "high"}]
    status = "ready" if not blockers and score >= 85 else "conditional" if score >= 65 else "blocked"

    latest_audit = None
    if database_ok:
        row = db.scalar(select(CrmActivity).where(
            CrmActivity.organization_id == principal.organization_id,
        ).order_by(CrmActivity.created_at.desc()))
        if row:
            latest_audit = {"type": row.activity_type, "summary": row.summary, "created_at": row.created_at}

    return {
        "generated_at": datetime.now(timezone.utc),
        "status": status,
        "score": score,
        "blocker_count": len(blockers),
        "checks": checks,
        "missing_routes": missing_routes,
        "providers": providers,
        "workspace": {
            "leads": lead_count,
            "properties": property_count,
            "buyers": buyer_count,
            "deals": deal_count,
        },
        "jobs": jobs,
        "owner_pages": OWNER_PAGES,
        "latest_audit": latest_audit,
        "launch_policy": {
            "automatic_production_launch": False,
            "owner_approval_required": True,
            "message": "Launch remains owner-controlled. Critical and high blockers should be cleared before live outreach or contract execution.",
        },
    }

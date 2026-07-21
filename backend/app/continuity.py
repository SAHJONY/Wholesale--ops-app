from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity
from .database import get_db

router = APIRouter(prefix="/continuity", tags=["backup and recovery continuity"])


def _configured(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _provider() -> str:
    url = (os.getenv("DATABASE_URL") or "").lower()
    if "neon.tech" in url:
        return "neon"
    if "supabase" in url:
        return "supabase"
    if url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        return "postgresql"
    return "unknown"


def _recent_drills(db: Session, organization_id: int) -> list[CrmActivity]:
    return list(db.scalars(
        select(CrmActivity)
        .where(
            CrmActivity.organization_id == organization_id,
            CrmActivity.activity_type == "continuity_restore_drill",
        )
        .order_by(CrmActivity.created_at.desc())
        .limit(20)
    ).all())


@router.get("/snapshot")
def snapshot(
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    database_ok = False
    database_error = None
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # pragma: no cover - environment specific
        database_error = type(exc).__name__

    drills = _recent_drills(db, principal.organization_id)
    last_success = next((item for item in drills if (item.metadata_json or {}).get("status") == "passed"), None)
    last_success_at = last_success.created_at if last_success else None
    drill_due = last_success_at is None or last_success_at < datetime.now(timezone.utc) - timedelta(days=90)

    provider = _provider()
    provider_api_ready = _configured("NEON_API_KEY") and _configured("NEON_PROJECT_ID") if provider == "neon" else False
    offsite_ready = _configured("S3_BUCKET") and _configured("S3_ACCESS_KEY_ID") and _configured("S3_SECRET_ACCESS_KEY")

    controls = {
        "database_connection": database_ok,
        "provider_identified": provider != "unknown",
        "provider_api_configured": provider_api_ready,
        "offsite_export_storage": offsite_ready,
        "restore_drill_current": not drill_due,
        "migration_guard_present": True,
    }
    ready_count = sum(1 for value in controls.values() if value)

    return {
        "status": "ready" if ready_count == len(controls) else "degraded",
        "generated_at": datetime.now(timezone.utc),
        "provider": provider,
        "database": {"ok": database_ok, "error": database_error},
        "objectives": {
            "rpo_hours": int(os.getenv("CONTINUITY_RPO_HOURS") or "24"),
            "rto_hours": int(os.getenv("CONTINUITY_RTO_HOURS") or "8"),
            "restore_drill_interval_days": 90,
        },
        "controls": controls,
        "summary": {
            "controls_ready": ready_count,
            "controls_total": len(controls),
            "restore_drill_due": drill_due,
            "last_successful_drill_at": last_success_at,
        },
        "drills": [
            {
                "id": item.id,
                "status": (item.metadata_json or {}).get("status", "unknown"),
                "environment": (item.metadata_json or {}).get("environment", "staging"),
                "recovery_minutes": (item.metadata_json or {}).get("recovery_minutes"),
                "evidence_reference": (item.metadata_json or {}).get("evidence_reference"),
                "notes": (item.metadata_json or {}).get("notes"),
                "recorded_at": item.created_at,
            }
            for item in drills
        ],
        "safety": {
            "automatic_restore_enabled": False,
            "message": "Production restores require explicit owner approval and provider-console execution.",
        },
    }


@router.post("/restore-drills")
def record_restore_drill(
    payload: dict,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    status = str(payload.get("status") or "").strip().lower()
    environment = str(payload.get("environment") or "staging").strip().lower()
    if status not in {"passed", "failed", "partial"}:
        raise HTTPException(422, "status must be passed, failed, or partial")
    if environment == "production":
        raise HTTPException(422, "Record production restore evidence only after an independently approved provider-console procedure")

    recovery_minutes = payload.get("recovery_minutes")
    if recovery_minutes is not None:
        recovery_minutes = max(0, int(recovery_minutes))

    activity = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="continuity_restore_drill",
        summary=f"Restore drill recorded as {status}",
        metadata_json={
            "status": status,
            "environment": environment,
            "recovery_minutes": recovery_minutes,
            "evidence_reference": str(payload.get("evidence_reference") or "").strip() or None,
            "notes": str(payload.get("notes") or "").strip() or None,
        },
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {"id": activity.id, "recorded": True, "status": status, "environment": environment}

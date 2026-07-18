from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .acquisition_worker_models import AcquisitionAutomationRun
from .database import get_db
from .models import Lead

router = APIRouter(prefix="/acquisition-worker", tags=["autonomous acquisition worker"])


def _linked_lead_ids(db: Session, organization_id: int) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(AcquisitionAutomationRun).where(
        AcquisitionAutomationRun.organization_id == principal.organization_id,
    ).order_by(AcquisitionAutomationRun.updated_at.desc()).limit(100)).all()
    counts = dict(db.execute(select(
        AcquisitionAutomationRun.status, func.count(AcquisitionAutomationRun.id),
    ).where(AcquisitionAutomationRun.organization_id == principal.organization_id).group_by(
        AcquisitionAutomationRun.status,
    )).all())
    return {
        "counts": counts,
        "provider_readiness": {
            "attom": bool(os.getenv("ATTOM_API_KEY")),
            "batchdata": bool(os.getenv("BATCHDATA_API_KEY") and os.getenv("BATCHDATA_SKIPTRACE_URL")),
        },
        "runs": [{
            "id": row.id,
            "lead_id": row.lead_id,
            "property_id": row.property_id,
            "status": row.status,
            "current_step": row.current_step,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "result": row.result_json,
            "updated_at": row.updated_at,
            "completed_at": row.completed_at,
        } for row in rows],
    }


async def _run_one(db: Session, principal: Principal, lead: Lead, force: bool = False):
    try:
        from .acquisition_worker import _process_one
    except Exception as exc:
        raise HTTPException(503, f"Acquisition worker dependency failed to load: {type(exc).__name__}: {exc}") from exc
    return await _process_one(db, principal, lead, force=force)


@router.post("/leads/{lead_id}/run")
async def run_lead(
    lead_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    if lead_id not in _linked_lead_ids(db, principal.organization_id):
        raise HTTPException(404, "Lead not found in this workspace")
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return await _run_one(db, principal, lead, force=bool((payload or {}).get("force")))


@router.post("/run-pending")
async def run_pending(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    limit = max(1, min(25, int((payload or {}).get("limit") or 10)))
    linked = _linked_lead_ids(db, principal.organization_id)
    if not linked:
        return {"processed": 0, "results": []}
    completed_ids = set(db.scalars(select(AcquisitionAutomationRun.lead_id).where(
        AcquisitionAutomationRun.organization_id == principal.organization_id,
        AcquisitionAutomationRun.status == "completed",
    )).all())
    leads = db.scalars(select(Lead).where(
        Lead.id.in_(linked), Lead.id.not_in(completed_ids),
    ).order_by(Lead.created_at).limit(limit)).all()
    results = []
    for lead in leads:
        try:
            results.append(await _run_one(db, principal, lead))
        except HTTPException as exc:
            db.rollback()
            results.append({"lead_id": lead.id, "status": "failed", "error": str(exc.detail)})
        except Exception as exc:
            db.rollback()
            results.append({"lead_id": lead.id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {"processed": len(results), "results": results}

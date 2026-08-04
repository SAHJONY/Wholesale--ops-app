from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .acquisition_worker import _process_one
from .acquisition_worker_models import AcquisitionAutomationRun
from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Buyer, Lead
from .national_intelligence import _refresh as refresh_national_intelligence
from .property_data import property_data_configured
from .national_intelligence_models import PropertyIntelligenceScore

router = APIRouter(prefix="/real-estate-intelligence", tags=["integrated real estate intelligence platform"])


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _provider_readiness() -> dict:
    return {
        "property_data": property_data_configured(),
        "contact_data": bool(os.getenv("BATCHDATA_API_KEY") and os.getenv("BATCHDATA_SKIPTRACE_URL")),
        "county_verification": True,
        "maps": bool(os.getenv("GOOGLE_MAPS_API_KEY")),
        "fema": True,
    }


def _snapshot(db: Session, principal: Principal) -> dict:
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    buyer_ids = _linked_ids(db, principal.organization_id, "buyer")
    run_counts = dict(db.execute(select(
        AcquisitionAutomationRun.status,
        func.count(AcquisitionAutomationRun.id),
    ).where(
        AcquisitionAutomationRun.organization_id == principal.organization_id,
    ).group_by(AcquisitionAutomationRun.status)).all())
    scores = db.scalars(select(PropertyIntelligenceScore).where(
        PropertyIntelligenceScore.organization_id == principal.organization_id,
    ).order_by(PropertyIntelligenceScore.opportunity_score.desc()).limit(250)).all()
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    providers = _provider_readiness()
    verified_buyers = sum(1 for buyer in buyers if buyer.proof_of_funds_verified)
    high_priority = [row for row in scores if row.opportunity_score >= 70]
    workflow = {
        "lead_processing": bool(lead_ids),
        "property_enrichment": providers["property_data"],
        "contact_enrichment": providers["contact_data"],
        "county_verification": True,
        "buyer_intelligence": bool(buyer_ids),
        "opportunity_ranking": bool(scores),
    }
    return {
        "generated_at": datetime.now(timezone.utc),
        "status": "active" if any(workflow.values()) else "setup",
        "providers": providers,
        "workflow": workflow,
        "summary": {
            "leads": len(lead_ids),
            "buyers": len(buyer_ids),
            "verified_buyers": verified_buyers,
            "scored_properties": len(scores),
            "high_priority": len(high_priority),
            "projected_assignment_fees": round(sum(float(row.projected_assignment_fee or 0) for row in scores), 2),
        },
        "acquisition_runs": run_counts,
        "opportunities": [{
            "property_id": row.property_id,
            "lead_id": row.lead_id,
            "market": row.market_key,
            "opportunity_score": row.opportunity_score,
            "distress_score": row.distress_score,
            "equity_score": row.equity_score,
            "buyer_demand_score": row.buyer_demand_score,
            "data_confidence": row.data_confidence,
            "ownership_verified": row.ownership_verified,
            "projected_assignment_fee": row.projected_assignment_fee,
            "reasons": row.reasons_json or [],
            "warnings": row.warnings_json or [],
            "source_summary": row.source_summary_json or {},
        } for row in scores[:100]],
        "policy": {
            "texas_excluded": True,
            "county_verification_required_for_contract_critical_ownership": True,
            "live_outreach_requires_compliance_and_owner_approval": True,
        },
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _snapshot(db, principal)


@router.post("/run")
async def run_pipeline(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    options = payload or {}
    limit = max(1, min(25, int(options.get("limit") or 10)))
    force = bool(options.get("force"))
    linked = _linked_ids(db, principal.organization_id, "lead")
    leads = db.scalars(select(Lead).where(Lead.id.in_(linked)).order_by(Lead.created_at).limit(limit)).all() if linked else []
    processed = []
    for lead in leads:
        if not lead.property or str(lead.property.state or "").upper() == "TX":
            processed.append({"lead_id": lead.id, "status": "skipped", "reason": "missing_property_or_texas_excluded"})
            continue
        try:
            processed.append(await _process_one(db, principal, lead, force=force))
        except Exception as exc:
            db.rollback()
            processed.append({"lead_id": lead.id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    intelligence_run = refresh_national_intelligence(db, principal, trigger="integrated_pipeline", limit=max(limit, 100))
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="real_estate_intelligence_pipeline_run",
        summary=f"Integrated intelligence pipeline processed {len(processed)} lead(s)",
        metadata_json={
            "processed": len(processed),
            "intelligence_run_id": intelligence_run.id,
            "properties_scored": intelligence_run.properties_scored,
            "high_priority_count": intelligence_run.high_priority_count,
        },
    ))
    db.commit()
    return {
        "processed": len(processed),
        "results": processed,
        "intelligence": {
            "run_id": intelligence_run.id,
            "properties_scored": intelligence_run.properties_scored,
            "high_priority_count": intelligence_run.high_priority_count,
        },
        "snapshot": _snapshot(db, principal),
    }

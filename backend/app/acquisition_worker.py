from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .acquisition_worker_models import AcquisitionAutomationRun
from .attom_adapter import AttomConfigurationError, AttomLookupError, lookup_attom_property
from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .batchdata_adapter import BatchDataConfigurationError, BatchDataLookupError, lookup_batchdata_contacts
from .county_queue_models import CountyVerificationCase
from .database import get_db
from .event_bus import emit_event
from .intelligence_ingest import ingest_provider_facts
from .models import Lead
from .services import calculate_mao, lead_score

router = APIRouter(prefix="/acquisition-worker", tags=["autonomous acquisition worker"])


def _linked_lead_ids(db: Session, organization_id: int) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())


def _get_or_create_run(db: Session, organization_id: int, lead: Lead) -> AcquisitionAutomationRun:
    run = db.scalar(select(AcquisitionAutomationRun).where(
        AcquisitionAutomationRun.organization_id == organization_id,
        AcquisitionAutomationRun.lead_id == lead.id,
    ))
    if not run:
        run = AcquisitionAutomationRun(
            organization_id=organization_id,
            lead_id=lead.id,
            property_id=lead.property.id,
        )
        db.add(run)
        db.flush()
    return run


def _address_parts(lead: Lead) -> tuple[str, str]:
    prop = lead.property
    return (
        str(prop.address or "").strip(),
        ", ".join(part for part in (prop.city, prop.state, prop.zip_code) if part),
    )


def _attom_facts(evidence: dict) -> dict:
    prop = evidence.get("property") or {}
    owner = evidence.get("owner") or {}
    valuation = evidence.get("valuation") or {}
    sale = evidence.get("last_sale") or {}
    identifiers = evidence.get("identifiers") or {}
    return {
        "address": prop.get("address"), "city": prop.get("city"), "state": prop.get("state"),
        "zip_code": prop.get("zip_code"), "property_type": prop.get("property_type"),
        "bedrooms": prop.get("bedrooms"), "bathrooms": prop.get("bathrooms"), "sqft": prop.get("sqft"),
        "latitude": prop.get("latitude"), "longitude": prop.get("longitude"),
        "attom_id": identifiers.get("attom_id"), "apn": identifiers.get("apn"), "fips": identifiers.get("fips"),
        "owner_name": owner.get("name"), "owner_mailing_address": owner.get("mailing_address"),
        "absentee_owner": owner.get("absentee_owner"), "assessed_value": valuation.get("assessed_value"),
        "market_value": valuation.get("market_value"), "tax_amount": valuation.get("tax_amount"),
        "last_sale_price": sale.get("price"), "last_sale_date": sale.get("date"),
    }


def _batch_facts(evidence: dict) -> dict:
    safe = evidence.get("safe_phone_candidates") or []
    emails = evidence.get("emails") or []
    return {
        "owner_name": evidence.get("owner_name"),
        "phone": safe[0].get("number") if safe else None,
        "phones": evidence.get("phones") or [],
        "email": emails[0].get("email") if emails else None,
        "emails": emails,
        "blocked_phones": evidence.get("blocked_phone_candidates") or [],
        "outreach_allowed": bool(evidence.get("outreach_allowed")),
    }


def _ensure_county_case(db: Session, organization_id: int, lead: Lead, evidence: dict) -> int | None:
    owner = evidence.get("owner") or {}
    if not owner.get("name"):
        return None
    existing = db.scalar(select(CountyVerificationCase).where(
        CountyVerificationCase.organization_id == organization_id,
        CountyVerificationCase.lead_id == lead.id,
        CountyVerificationCase.status.in_(["pending", "assigned", "needs_review"]),
    ))
    if existing:
        return existing.id
    confidence = float(evidence.get("confidence") or 0)
    case = CountyVerificationCase(
        organization_id=organization_id,
        lead_id=lead.id,
        property_id=lead.property.id,
        state=str(lead.property.state or "").upper(),
        status="pending",
        priority=85 if confidence >= 80 else 70,
        confidence=min(79, confidence),
        due_at=datetime.utcnow() + timedelta(days=2),
        source_type="attom",
        source_reference=str(evidence.get("raw_reference") or "") or None,
        proposed_evidence={
            "owner_name": owner.get("name"),
            "owner_mailing_address": owner.get("mailing_address"),
            "apn": (evidence.get("identifiers") or {}).get("apn"),
        },
        reviewer_notes="Verify against the official county assessor or recorder before promotion.",
    )
    db.add(case)
    db.flush()
    emit_event(
        db, organization_id, "CountyVerificationRequested", "lead", lead.id,
        payload={"case_id": case.id, "property_id": lead.property.id, "source": "attom"},
        source="acquisition_worker", event_key=f"county-request:{organization_id}:{lead.id}",
    )
    return case.id


async def _process_one(db: Session, principal: Principal, lead: Lead, force: bool = False) -> dict:
    if not lead.property:
        raise HTTPException(404, "Lead property not found")
    if str(lead.property.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    run = _get_or_create_run(db, principal.organization_id, lead)
    if run.status == "completed" and not force:
        return {"lead_id": lead.id, "run_id": run.id, "status": "already_completed", "result": run.result_json}

    run.status = "running"
    run.current_step = "starting"
    run.attempts += 1
    run.started_at = datetime.utcnow()
    run.last_error = None
    result: dict = {"attom": {}, "batchdata": {}, "county_case_id": None, "qualification": {}}

    address1, address2 = _address_parts(lead)
    if not address1 or not address2:
        run.status = "blocked"
        run.current_step = "address_validation"
        run.last_error = "Complete property address is required"
        db.commit()
        return {"lead_id": lead.id, "run_id": run.id, "status": run.status, "error": run.last_error}

    run.current_step = "attom_enrichment"
    try:
        evidence = await lookup_attom_property(address1, address2)
        ingestion = ingest_provider_facts(
            db, principal.organization_id, "property", lead.property.id, "attom", _attom_facts(evidence),
            confidence=float(evidence.get("confidence") or 0),
            source_reference=str(evidence.get("raw_reference") or "") or None,
            verification_status="partially_verified",
            metadata={"automation_run_id": run.id, "lead_id": lead.id},
        )
        result["attom"] = {"status": "completed", **ingestion}
        result["county_case_id"] = _ensure_county_case(db, principal.organization_id, lead, evidence)
    except AttomConfigurationError as exc:
        result["attom"] = {"status": "waiting_configuration", "error": str(exc)}
    except AttomLookupError as exc:
        result["attom"] = {"status": "provider_error", "error": str(exc)}

    run.current_step = "batchdata_enrichment"
    try:
        evidence = await lookup_batchdata_contacts(
            address=lead.property.address, city=lead.property.city, state=lead.property.state,
            zip_code=lead.property.zip_code, owner_name=lead.seller_name,
        )
        ingestion = ingest_provider_facts(
            db, principal.organization_id, "seller", lead.id, "batchdata", _batch_facts(evidence),
            confidence=float(evidence.get("confidence") or 0),
            source_reference=str(evidence.get("raw_reference") or "") or None,
            verification_status="partially_verified",
            metadata={"automation_run_id": run.id, "property_id": lead.property.id},
        )
        result["batchdata"] = {"status": "completed", **ingestion}
    except BatchDataConfigurationError as exc:
        result["batchdata"] = {"status": "waiting_configuration", "error": str(exc)}
    except BatchDataLookupError as exc:
        result["batchdata"] = {"status": "provider_error", "error": str(exc)}

    run.current_step = "qualification_review"
    if lead.property.arv is not None and lead.property.repairs is not None:
        lead.property.mao = calculate_mao(lead.property.arv, lead.property.repairs)
    score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
    suggested_status = "qualified" if score >= 70 else "nurture" if score >= 45 else "new"
    result["qualification"] = {"score": score, "suggested_status": suggested_status, "mao": lead.property.mao}
    if score >= 70:
        emit_event(
            db, principal.organization_id, "LeadQualified", "lead", lead.id,
            payload={"property_id": lead.property.id, "lead_score": score, "mao": lead.property.mao},
            source="acquisition_worker", event_key=f"lead-qualified:{principal.organization_id}:{lead.id}:{int(score)}",
        )
    follow_up = db.scalar(select(FollowUpTask).where(
        FollowUpTask.organization_id == principal.organization_id,
        FollowUpTask.lead_id == lead.id,
        FollowUpTask.status == "open",
    ))
    if not follow_up:
        db.add(FollowUpTask(
            organization_id=principal.organization_id, lead_id=lead.id, assigned_user_id=principal.user_id,
            title=f"Verify motivation and ownership for {lead.seller_name}",
            priority=max(50, min(100, int(score))), due_at=datetime.utcnow() + timedelta(hours=24),
            notes="Created by the autonomous acquisition worker. Human verification remains required.",
        ))

    run.current_step = "completed"
    run.status = "completed" if any(result[name].get("status") == "completed" for name in ("attom", "batchdata")) else "waiting_configuration"
    run.result_json = result
    run.completed_at = datetime.utcnow()
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id,
        activity_type="acquisition_automation_processed",
        summary=f"Autonomous acquisition processing finished with status {run.status}",
        metadata_json={"run_id": run.id, "result": result},
    ))
    db.commit()
    return {"lead_id": lead.id, "run_id": run.id, "status": run.status, "result": result}


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
            "id": row.id, "lead_id": row.lead_id, "property_id": row.property_id,
            "status": row.status, "current_step": row.current_step, "attempts": row.attempts,
            "last_error": row.last_error, "result": row.result_json,
            "updated_at": row.updated_at, "completed_at": row.completed_at,
        } for row in rows],
    }


@router.post("/leads/{lead_id}/run")
async def run_lead(lead_id: int, payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    if lead_id not in _linked_lead_ids(db, principal.organization_id):
        raise HTTPException(404, "Lead not found in this workspace")
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return await _process_one(db, principal, lead, force=bool((payload or {}).get("force")))


@router.post("/run-pending")
async def run_pending(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
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
            results.append(await _process_one(db, principal, lead))
        except Exception as exc:
            db.rollback()
            results.append({"lead_id": lead.id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {"processed": len(results), "results": results}

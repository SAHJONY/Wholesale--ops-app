from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .county_queue_models import CountyVerificationCase
from .county_verification import verify_county_ownership
from .crm import _assert_linked
from .database import get_db
from .event_bus import emit_event
from .models import Lead

router = APIRouter(prefix="/county-queue", tags=["county verification queue"])
AUTHORITATIVE_SOURCE_TYPES = {"assessor", "recorder", "clerk", "tax_collector"}
RESEARCH_SOURCE_TYPES = {"reverse_address_research", "people_search"}


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    cases = db.scalars(select(CountyVerificationCase).where(
        CountyVerificationCase.organization_id == principal.organization_id
    ).order_by(CountyVerificationCase.priority.desc(), CountyVerificationCase.created_at)).all()
    counts = dict(db.execute(select(CountyVerificationCase.status, func.count(CountyVerificationCase.id)).where(
        CountyVerificationCase.organization_id == principal.organization_id
    ).group_by(CountyVerificationCase.status)).all())
    return {
        "generated_at": now,
        "counts": counts,
        "overdue": sum(1 for c in cases if c.status in {"pending", "assigned", "needs_review"} and c.due_at and c.due_at < now),
        "cases": [{
            "id": c.id, "lead_id": c.lead_id, "property_id": c.property_id,
            "county": c.county, "state": c.state, "status": c.status,
            "priority": c.priority, "confidence": c.confidence,
            "assigned_to_user_id": c.assigned_to_user_id, "due_at": c.due_at,
            "source_type": c.source_type, "source_reference": c.source_reference,
            "proposed_evidence": c.proposed_evidence, "reviewer_notes": c.reviewer_notes,
            "created_at": c.created_at, "reviewed_at": c.reviewed_at,
        } for c in cases[:200]],
    }


@router.post("/leads/{lead_id}")
def create_case(lead_id: int, payload: dict | None = None, principal: Principal = Depends(require_role("acquisitions")), db: Session = Depends(get_db)):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead or not lead.property:
        raise HTTPException(404, "Lead property not found")
    if str(lead.property.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    payload = payload or {}
    source_type = str(payload.get("source_type") or "manual_research").strip().lower()
    source_reference = str(payload.get("source_reference") or "").strip()
    if source_reference and not source_reference.lower().startswith("https://"):
        raise HTTPException(422, "Source reference must use HTTPS")
    confidence = max(0, min(100, float(payload.get("confidence") or 0)))
    if source_type in RESEARCH_SOURCE_TYPES:
        confidence = min(confidence, 40)
    elif source_type not in AUTHORITATIVE_SOURCE_TYPES | {"manual_research"}:
        raise HTTPException(422, "Unsupported verification source type")
    existing = db.scalar(select(CountyVerificationCase).where(
        CountyVerificationCase.organization_id == principal.organization_id,
        CountyVerificationCase.lead_id == lead_id,
        CountyVerificationCase.status.in_(["pending", "assigned", "needs_review"]),
    ))
    if existing:
        if source_type in RESEARCH_SOURCE_TYPES:
            existing.source_type = source_type
            existing.source_reference = source_reference
            existing.confidence = confidence
            existing.status = "needs_review"
            existing.proposed_evidence = payload.get("proposed_evidence") or {}
            existing.updated_at = datetime.now(timezone.utc)
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return {
                "case_id": existing.id,
                "status": existing.status,
                "created": False,
                "updated": True,
            }
        return {"case_id": existing.id, "status": existing.status, "created": False}
    case = CountyVerificationCase(
        organization_id=principal.organization_id,
        lead_id=lead.id,
        property_id=lead.property.id,
        county=str(payload.get("county") or "").strip() or None,
        state=str(lead.property.state).upper(),
        priority=max(1, min(100, int(payload.get("priority") or 70))),
        confidence=confidence,
        due_at=datetime.now(timezone.utc) + timedelta(days=max(1, int(payload.get("due_days") or 3))),
        source_type=source_type,
        source_reference=source_reference or None,
        proposed_evidence=payload.get("proposed_evidence") or {},
    )
    db.add(case)
    db.flush()
    emit_event(db, principal.organization_id, "CountyVerificationRequested", "property", lead.property.id,
               payload={"case_id": case.id, "lead_id": lead.id, "priority": case.priority},
               source="county_queue", event_key=f"county-case:{case.id}:requested")
    db.commit()
    return {"case_id": case.id, "status": case.status, "created": True}


@router.patch("/{case_id}")
def update_case(case_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    case = db.scalar(select(CountyVerificationCase).where(
        CountyVerificationCase.id == case_id,
        CountyVerificationCase.organization_id == principal.organization_id,
    ))
    if not case:
        raise HTTPException(404, "County verification case not found")
    if "assigned_to_user_id" in payload:
        case.assigned_to_user_id = int(payload["assigned_to_user_id"]) if payload["assigned_to_user_id"] else None
        case.status = "assigned" if case.assigned_to_user_id else "pending"
    if "priority" in payload:
        case.priority = max(1, min(100, int(payload["priority"])))
    if "confidence" in payload:
        case.confidence = max(0, min(100, float(payload["confidence"])))
    if "reviewer_notes" in payload:
        case.reviewer_notes = str(payload["reviewer_notes"] or "") or None
    if "proposed_evidence" in payload and isinstance(payload["proposed_evidence"], dict):
        case.proposed_evidence = payload["proposed_evidence"]
        case.status = "needs_review"
    db.commit()
    return {"case_id": case.id, "status": case.status}


@router.post("/{case_id}/decision")
def decide_case(case_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    case = db.scalar(select(CountyVerificationCase).where(
        CountyVerificationCase.id == case_id,
        CountyVerificationCase.organization_id == principal.organization_id,
    ))
    if not case:
        raise HTTPException(404, "County verification case not found")
    decision = str(payload.get("decision") or "").lower()
    if decision not in {"verified", "rejected", "needs_review"}:
        raise HTTPException(422, "Decision must be verified, rejected, or needs_review")
    evidence = payload.get("evidence") or case.proposed_evidence or {}
    if decision == "verified":
        if case.confidence < 80:
            raise HTTPException(422, "County evidence confidence must be at least 80 before verification")
        evidence = {**evidence, "source_reference": evidence.get("source_reference") or case.source_reference,
                    "record_type": evidence.get("record_type") or case.source_type or "assessor",
                    "county": evidence.get("county") or case.county}
        verify_county_ownership(case.lead_id, evidence, principal, db)
    case.status = decision
    case.reviewed_by_user_id = principal.user_id
    case.reviewed_at = datetime.now(timezone.utc)
    case.reviewer_notes = str(payload.get("reviewer_notes") or case.reviewer_notes or "") or None
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id,
        lead_id=case.lead_id, activity_type=f"county_case_{decision}",
        summary=f"County verification case #{case.id} marked {decision}",
        metadata_json={"case_id": case.id, "confidence": case.confidence, "source_reference": case.source_reference},
    ))
    db.commit()
    return {"case_id": case.id, "status": case.status, "reviewed_at": case.reviewed_at}

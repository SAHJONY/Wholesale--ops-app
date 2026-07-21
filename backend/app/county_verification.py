from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity
from .crm import _assert_linked
from .database import get_db
from .event_bus import emit_event
from .intelligence_models import CanonicalEntity, IntelligenceConflict, IntelligenceFact
from .models import Lead

router = APIRouter(prefix="/county-verification", tags=["county ownership verification"])


def _upsert_fact(db: Session, organization_id: int, entity_type: str, entity_id: int, field_name: str, value, source_reference: str, metadata: dict):
    fact = db.scalar(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == organization_id,
        IntelligenceFact.entity_type == entity_type,
        IntelligenceFact.entity_id == entity_id,
        IntelligenceFact.field_name == field_name,
        IntelligenceFact.source == "county_record",
    ))
    if not fact:
        fact = IntelligenceFact(
            organization_id=organization_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            source="county_record",
        )
        db.add(fact)
    fact.value_json = {"value": value}
    fact.source_reference = source_reference
    fact.confidence = 100
    fact.verification_status = "verified"
    fact.observed_at = datetime.now(timezone.utc)
    fact.metadata_json = metadata
    db.flush()
    return fact


def _rebuild(db: Session, organization_id: int, entity_type: str, entity_id: int):
    canonical = db.scalar(select(CanonicalEntity).where(
        CanonicalEntity.organization_id == organization_id,
        CanonicalEntity.entity_type == entity_type,
        CanonicalEntity.entity_id == entity_id,
    ))
    if not canonical:
        canonical = CanonicalEntity(organization_id=organization_id, entity_type=entity_type, entity_id=entity_id)
        db.add(canonical)
        db.flush()
    facts = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == organization_id,
        IntelligenceFact.entity_type == entity_type,
        IntelligenceFact.entity_id == entity_id,
    ).order_by(IntelligenceFact.field_name, IntelligenceFact.confidence.desc())).all()
    grouped = {}
    for fact in facts:
        grouped.setdefault(fact.field_name, []).append(fact)
    data = {}
    conflict_count = 0
    scores = []
    for field_name, rows in grouped.items():
        verified = [row for row in rows if row.verification_status == "verified"]
        winner = (verified or rows)[0]
        value = winner.value_json.get("value")
        data[field_name] = value
        scores.append(float(winner.confidence or 0))
        distinct = {repr(row.value_json.get("value")) for row in rows if row.value_json.get("value") not in (None, "")}
        conflict = db.scalar(select(IntelligenceConflict).where(
            IntelligenceConflict.organization_id == organization_id,
            IntelligenceConflict.entity_type == entity_type,
            IntelligenceConflict.entity_id == entity_id,
            IntelligenceConflict.field_name == field_name,
            IntelligenceConflict.status == "open",
        ))
        if len(distinct) > 1:
            conflict_count += 1
            if not conflict:
                conflict = IntelligenceConflict(
                    organization_id=organization_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field_name=field_name,
                    status="open",
                    severity="high" if field_name in {"owner_name", "apn"} else "medium",
                )
                db.add(conflict)
            conflict.competing_values = [row.value_json.get("value") for row in rows]
        elif conflict:
            conflict.status = "resolved"
            conflict.resolution = "County-verified fact became canonical"
            conflict.resolved_at = datetime.now(timezone.utc)
    canonical.canonical_data = data
    canonical.source_count = len({fact.source for fact in facts})
    canonical.conflict_count = conflict_count
    canonical.confidence = round(sum(scores) / len(scores), 2) if scores else 0
    canonical.verification_status = "disputed" if conflict_count else ("verified" if facts and all(f.verification_status == "verified" for f in facts) else "partially_verified")
    canonical.last_verified_at = datetime.now(timezone.utc)
    return canonical


@router.post("/leads/{lead_id}/ownership")
def verify_county_ownership(
    lead_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead or not lead.property:
        raise HTTPException(404, "Lead property not found")
    if str(lead.property.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    owner_name = str(payload.get("owner_name") or "").strip()
    source_reference = str(payload.get("source_reference") or "").strip()
    record_type = str(payload.get("record_type") or "assessor").strip().lower()
    if not owner_name or not source_reference:
        raise HTTPException(422, "owner_name and source_reference are required")
    if record_type not in {"assessor", "recorder", "clerk", "tax_collector"}:
        raise HTTPException(422, "Unsupported county record type")
    metadata = {
        "record_type": record_type,
        "county": payload.get("county"),
        "state": lead.property.state,
        "record_date": payload.get("record_date"),
        "instrument_number": payload.get("instrument_number"),
        "verified_by_user_id": principal.user_id,
    }
    property_id = lead.property.id
    fields = {
        "owner_name": owner_name,
        "owner_mailing_address": payload.get("owner_mailing_address"),
        "apn": payload.get("apn"),
        "deed_type": payload.get("deed_type"),
        "instrument_number": payload.get("instrument_number"),
        "record_date": payload.get("record_date"),
    }
    written = []
    for field_name, value in fields.items():
        if value not in (None, ""):
            _upsert_fact(db, principal.organization_id, "property", property_id, field_name, value, source_reference, metadata)
            written.append(field_name)
    canonical = _rebuild(db, principal.organization_id, "property", property_id)
    event = emit_event(
        db,
        principal.organization_id,
        "EntityIntelligenceUpdated",
        "property",
        property_id,
        payload={"source": "county_record", "fields": written, "verification_status": canonical.verification_status},
        source="county_verification",
        event_key=f"county-verification:{property_id}:{source_reference}",
    )
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="county_ownership_verified",
        summary=f"County ownership verified as {owner_name}",
        metadata_json={"property_id": property_id, "source_reference": source_reference, "record_type": record_type, "fields": written, "event_id": event.id},
    ))
    db.commit()
    return {
        "lead_id": lead.id,
        "property_id": property_id,
        "owner_name": owner_name,
        "fields_written": written,
        "canonical_status": canonical.verification_status,
        "canonical_confidence": canonical.confidence,
        "conflict_count": canonical.conflict_count,
        "event_id": event.id,
    }

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .database import get_db
from .event_bus import emit_event
from .intelligence_models import CanonicalEntity, IntelligenceConflict, IntelligenceFact

router = APIRouter(prefix="/intelligence-platform", tags=["enterprise intelligence platform"])
ENTITY_TYPES = {"property", "seller", "buyer"}
VERIFICATION_STATES = {"unverified", "partially_verified", "verified", "disputed", "stale"}


def _entity(db: Session, principal: Principal, entity_type: str, entity_id: int) -> CanonicalEntity:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(422, "Entity type must be property, seller, or buyer")
    row = db.scalar(select(CanonicalEntity).where(
        CanonicalEntity.organization_id == principal.organization_id,
        CanonicalEntity.entity_type == entity_type,
        CanonicalEntity.entity_id == entity_id,
    ))
    if not row:
        row = CanonicalEntity(organization_id=principal.organization_id, entity_type=entity_type, entity_id=entity_id)
        db.add(row)
        db.flush()
    return row


def _rebuild(db: Session, canonical: CanonicalEntity) -> None:
    facts = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == canonical.organization_id,
        IntelligenceFact.entity_type == canonical.entity_type,
        IntelligenceFact.entity_id == canonical.entity_id,
    ).order_by(IntelligenceFact.field_name, IntelligenceFact.confidence.desc())).all()
    grouped = {}
    for fact in facts:
        grouped.setdefault(fact.field_name, []).append(fact)
    data = {}
    conflicts = 0
    scores = []
    for field_name, rows in grouped.items():
        verified = [row for row in rows if row.verification_status == "verified"]
        winner = (verified or rows)[0]
        data[field_name] = winner.value_json.get("value")
        distinct = {repr(row.value_json.get("value")) for row in rows if row.value_json.get("value") not in (None, "")}
        if len(distinct) > 1:
            conflicts += 1
        scores.append(float(winner.confidence or 0))
    canonical.canonical_data = data
    canonical.source_count = len({fact.source for fact in facts})
    canonical.conflict_count = conflicts
    canonical.confidence = round(sum(scores) / len(scores), 2) if scores else 0
    canonical.verification_status = "disputed" if conflicts else ("verified" if facts and all(f.verification_status == "verified" for f in facts) else "partially_verified" if facts else "unverified")
    canonical.last_verified_at = max((fact.observed_at for fact in facts if fact.verification_status == "verified" and fact.observed_at), default=None)


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    entities = db.scalars(select(CanonicalEntity).where(CanonicalEntity.organization_id == principal.organization_id).order_by(CanonicalEntity.updated_at.desc()).limit(200)).all()
    fact_count = db.scalar(select(func.count(IntelligenceFact.id)).where(IntelligenceFact.organization_id == principal.organization_id)) or 0
    open_conflicts = db.scalar(select(func.count(IntelligenceConflict.id)).where(IntelligenceConflict.organization_id == principal.organization_id, IntelligenceConflict.status == "open")) or 0
    return {
        "generated_at": datetime.utcnow(),
        "entity_count": len(entities),
        "fact_count": fact_count,
        "open_conflicts": open_conflicts,
        "entities": [{
            "id": entity.id,
            "entity_type": entity.entity_type,
            "entity_id": entity.entity_id,
            "canonical_data": entity.canonical_data,
            "verification_status": entity.verification_status,
            "confidence": entity.confidence,
            "conflict_count": entity.conflict_count,
            "source_count": entity.source_count,
            "last_verified_at": entity.last_verified_at,
            "updated_at": entity.updated_at,
        } for entity in entities],
    }


@router.get("/{entity_type}/{entity_id}")
def detail(entity_type: str, entity_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    canonical = _entity(db, principal, entity_type, entity_id)
    facts = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == principal.organization_id,
        IntelligenceFact.entity_type == entity_type,
        IntelligenceFact.entity_id == entity_id,
    ).order_by(IntelligenceFact.field_name, IntelligenceFact.confidence.desc())).all()
    db.commit()
    return {
        "canonical": {"id": canonical.id, "data": canonical.canonical_data, "verification_status": canonical.verification_status, "confidence": canonical.confidence, "conflict_count": canonical.conflict_count, "source_count": canonical.source_count},
        "facts": [{"id": fact.id, "field_name": fact.field_name, "value": fact.value_json.get("value"), "source": fact.source, "source_reference": fact.source_reference, "confidence": fact.confidence, "verification_status": fact.verification_status, "observed_at": fact.observed_at} for fact in facts],
    }


@router.post("/{entity_type}/{entity_id}/facts")
def upsert_fact(entity_type: str, entity_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    canonical = _entity(db, principal, entity_type, entity_id)
    field_name = str(payload.get("field_name") or "").strip()
    source = str(payload.get("source") or "manual").strip().lower()
    if not field_name:
        raise HTTPException(422, "field_name is required")
    verification_status = str(payload.get("verification_status") or "unverified").strip().lower()
    if verification_status not in VERIFICATION_STATES:
        raise HTTPException(422, "Invalid verification status")
    fact = db.scalar(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == principal.organization_id,
        IntelligenceFact.entity_type == entity_type,
        IntelligenceFact.entity_id == entity_id,
        IntelligenceFact.field_name == field_name,
        IntelligenceFact.source == source,
    ))
    if not fact:
        fact = IntelligenceFact(organization_id=principal.organization_id, entity_type=entity_type, entity_id=entity_id, field_name=field_name, source=source)
        db.add(fact)
    fact.value_json = {"value": payload.get("value")}
    fact.source_reference = str(payload.get("source_reference") or "").strip() or None
    fact.confidence = max(0, min(100, float(payload.get("confidence") or 0)))
    fact.verification_status = verification_status
    fact.observed_at = datetime.utcnow()
    fact.metadata_json = payload.get("metadata") or {}
    db.flush()
    _rebuild(db, canonical)
    event = emit_event(
        db,
        principal.organization_id,
        "EntityIntelligenceUpdated",
        entity_type,
        entity_id,
        payload={"field_name": field_name, "source": source, "verification_status": verification_status, "confidence": fact.confidence},
        source="intelligence_platform",
    )
    db.commit()
    return {"fact_id": fact.id, "canonical_id": canonical.id, "event_id": event.id, "verification_status": canonical.verification_status, "confidence": canonical.confidence, "conflict_count": canonical.conflict_count}


@router.post("/{entity_type}/{entity_id}/rebuild")
def rebuild(entity_type: str, entity_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    canonical = _entity(db, principal, entity_type, entity_id)
    _rebuild(db, canonical)
    db.commit()
    return {"canonical_id": canonical.id, "verification_status": canonical.verification_status, "confidence": canonical.confidence, "conflict_count": canonical.conflict_count, "source_count": canonical.source_count}

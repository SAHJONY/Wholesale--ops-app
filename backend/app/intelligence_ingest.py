from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .event_bus import emit_event
from .intelligence_models import CanonicalEntity, IntelligenceConflict, IntelligenceFact
from .intelligence_platform import _rebuild


def _canonical(db: Session, organization_id: int, entity_type: str, entity_id: int) -> CanonicalEntity:
    row = db.scalar(select(CanonicalEntity).where(
        CanonicalEntity.organization_id == organization_id,
        CanonicalEntity.entity_type == entity_type,
        CanonicalEntity.entity_id == entity_id,
    ))
    if not row:
        row = CanonicalEntity(organization_id=organization_id, entity_type=entity_type, entity_id=entity_id)
        db.add(row)
        db.flush()
    return row


def ingest_provider_facts(
    db: Session,
    organization_id: int,
    entity_type: str,
    entity_id: int,
    source: str,
    facts: dict,
    *,
    confidence: float = 0,
    source_reference: str | None = None,
    verification_status: str = "unverified",
    observed_at: datetime | None = None,
    metadata: dict | None = None,
) -> dict:
    canonical = _canonical(db, organization_id, entity_type, entity_id)
    observed = observed_at or datetime.now(timezone.utc)
    written = 0
    for field_name, value in facts.items():
        if value in (None, "", [], {}):
            continue
        fact = db.scalar(select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_type == entity_type,
            IntelligenceFact.entity_id == entity_id,
            IntelligenceFact.field_name == field_name,
            IntelligenceFact.source == source,
        ))
        if not fact:
            fact = IntelligenceFact(
                organization_id=organization_id,
                entity_type=entity_type,
                entity_id=entity_id,
                field_name=field_name,
                source=source,
            )
            db.add(fact)
        fact.value_json = {"value": value}
        fact.source_reference = source_reference
        fact.confidence = max(0, min(100, float(confidence or 0)))
        fact.verification_status = verification_status
        fact.observed_at = observed
        fact.metadata_json = metadata or {}
        written += 1
    db.flush()
    _rebuild(db, canonical)
    _sync_conflicts(db, canonical)
    event = emit_event(
        db,
        organization_id,
        "EntityIntelligenceUpdated",
        entity_type,
        entity_id,
        payload={"source": source, "facts_written": written, "verification_status": canonical.verification_status, "confidence": canonical.confidence},
        source=f"{source}_adapter",
        event_key=f"intelligence:{organization_id}:{entity_type}:{entity_id}:{source}:{observed.isoformat()}",
    )
    return {"canonical_id": canonical.id, "facts_written": written, "event_id": event.id, "verification_status": canonical.verification_status, "conflict_count": canonical.conflict_count}


def _sync_conflicts(db: Session, canonical: CanonicalEntity) -> None:
    facts = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == canonical.organization_id,
        IntelligenceFact.entity_type == canonical.entity_type,
        IntelligenceFact.entity_id == canonical.entity_id,
    )).all()
    grouped: dict[str, list[IntelligenceFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.field_name, []).append(fact)
    open_rows = db.scalars(select(IntelligenceConflict).where(
        IntelligenceConflict.organization_id == canonical.organization_id,
        IntelligenceConflict.entity_type == canonical.entity_type,
        IntelligenceConflict.entity_id == canonical.entity_id,
        IntelligenceConflict.status == "open",
    )).all()
    by_field = {row.field_name: row for row in open_rows}
    conflicting_fields = set()
    for field_name, rows in grouped.items():
        values = []
        seen = set()
        for row in rows:
            value = row.value_json.get("value")
            marker = repr(value)
            if value not in (None, "") and marker not in seen:
                seen.add(marker)
                values.append({"value": value, "source": row.source, "confidence": row.confidence, "verification_status": row.verification_status})
        if len(values) > 1:
            conflicting_fields.add(field_name)
            conflict = by_field.get(field_name)
            if not conflict:
                conflict = IntelligenceConflict(
                    organization_id=canonical.organization_id,
                    entity_type=canonical.entity_type,
                    entity_id=canonical.entity_id,
                    field_name=field_name,
                )
                db.add(conflict)
            conflict.competing_values = values
            conflict.severity = "high" if field_name in {"owner_name", "phone", "email", "arv", "mortgage_balance"} else "medium"
    for field_name, conflict in by_field.items():
        if field_name not in conflicting_fields:
            conflict.status = "resolved"
            conflict.resolution = "Provider facts converged or conflicting fact was removed"
            conflict.resolved_at = datetime.now(timezone.utc)

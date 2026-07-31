from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .acquisition_intake_models import AcquisitionImportBatch
from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .event_bus import emit_event
from .models import Lead, Property

router = APIRouter(prefix="/acquisition-intake", tags=["autonomous acquisition intake"])

ALLOWED_SOURCES = {
    "propstream", "batchdata", "attom", "county", "mls", "fsbo",
    "facebook", "driving_for_dollars", "csv", "manual", "other",
}


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _address_key(address: str, city: str, state: str, zip_code: str) -> str:
    raw = "|".join((_clean(address), _clean(city), _clean(state).upper(), _clean(zip_code)))
    return re.sub(r"[^a-z0-9|]", "", raw.lower())


def _workspace_property_map(db: Session, organization_id: int) -> dict[str, tuple[Lead, Property]]:
    lead_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    if not lead_ids:
        return {}
    rows = db.execute(
        select(Lead, Property).join(Property, Property.lead_id == Lead.id).where(Lead.id.in_(lead_ids))
    ).all()
    return {
        _address_key(prop.address, prop.city, prop.state, prop.zip_code): (lead, prop)
        for lead, prop in rows
    }


def _normalize_record(record: dict, default_source: str) -> dict:
    address = _clean(record.get("address") or record.get("property_address") or record.get("street_address"))
    city = _clean(record.get("city") or record.get("property_city"))
    state = _clean(record.get("state") or record.get("property_state")).upper()
    zip_code = _clean(record.get("zip_code") or record.get("zip") or record.get("postal_code"))
    seller_name = _clean(record.get("seller_name") or record.get("owner_name") or record.get("owner") or "Unknown owner")
    phone = _clean(record.get("phone") or record.get("owner_phone"))
    email = _clean(record.get("email") or record.get("owner_email")) or None
    source = _clean(record.get("source") or default_source).lower()
    if source not in ALLOWED_SOURCES:
        source = "other"
    distress = record.get("distress_signals") or record.get("tags") or []
    if isinstance(distress, str):
        distress = [part.strip().lower().replace(" ", "_") for part in distress.split(",") if part.strip()]
    return {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "seller_name": seller_name,
        "phone": phone,
        "email": email,
        "source": source,
        "property_type": _clean(record.get("property_type") or "single_family").lower().replace(" ", "_"),
        "bedrooms": record.get("bedrooms") or record.get("beds"),
        "bathrooms": record.get("bathrooms") or record.get("baths"),
        "sqft": record.get("sqft") or record.get("square_feet"),
        "asking_price": record.get("asking_price") or record.get("list_price"),
        "arv": record.get("arv"),
        "repairs": record.get("repairs") or record.get("repair_estimate"),
        "distress_signals": list(dict.fromkeys(distress if isinstance(distress, list) else [])),
        "external_id": _clean(record.get("external_id") or record.get("record_id") or record.get("property_id")),
        "raw": record,
    }


def _number(value, cast=float):
    if value in (None, ""):
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from .autonomous_property_acquisition import acquisition_feed_status
    batches = db.scalars(select(AcquisitionImportBatch).where(
        AcquisitionImportBatch.organization_id == principal.organization_id
    ).order_by(AcquisitionImportBatch.created_at.desc()).limit(50)).all()
    totals = dict(db.execute(select(
        AcquisitionImportBatch.status, func.count(AcquisitionImportBatch.id)
    ).where(AcquisitionImportBatch.organization_id == principal.organization_id).group_by(
        AcquisitionImportBatch.status
    )).all())
    return {
        "counts": totals,
        "autonomous_feed": acquisition_feed_status(),
        "batches": [{
            "id": row.id, "source": row.source, "status": row.status,
            "records_received": row.records_received, "records_created": row.records_created,
            "records_updated": row.records_updated, "records_duplicate": row.records_duplicate,
            "records_rejected": row.records_rejected, "result": row.result_json,
            "created_at": row.created_at, "completed_at": row.completed_at,
        } for row in batches],
    }


@router.post("/import")
def import_records(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    source = _clean(payload.get("source") or "csv").lower()
    if source not in ALLOWED_SOURCES:
        raise HTTPException(422, "Unsupported acquisition source")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise HTTPException(422, "records must be a non-empty list")
    if len(records) > 1000:
        raise HTTPException(422, "A single import is limited to 1,000 records")
    review_only = bool(payload.get("_autonomous_review_only"))

    batch = AcquisitionImportBatch(
        organization_id=principal.organization_id,
        source=source,
        external_batch_id=_clean(payload.get("external_batch_id")) or None,
        records_received=len(records),
    )
    db.add(batch)
    db.flush()

    existing = _workspace_property_map(db, principal.organization_id)
    created = updated = duplicate = rejected = 0
    results = []

    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            rejected += 1
            results.append({"row": index, "status": "rejected", "reason": "record_not_object"})
            continue
        record = _normalize_record(raw, source)
        if not all((record["address"], record["city"], record["state"], record["zip_code"])):
            rejected += 1
            results.append({"row": index, "status": "rejected", "reason": "incomplete_address"})
            continue
        if record["state"] == "TX":
            rejected += 1
            results.append({"row": index, "status": "rejected", "reason": "texas_excluded"})
            continue

        key = _address_key(record["address"], record["city"], record["state"], record["zip_code"])
        match = existing.get(key)
        if match:
            lead, prop = match
            changed = {}
            if not lead.phone and record["phone"]:
                lead.phone = record["phone"]
                changed["phone"] = record["phone"]
            if not lead.email and record["email"]:
                lead.email = record["email"]
                changed["email"] = record["email"]
            for field in ("bedrooms", "bathrooms", "sqft", "asking_price", "arv", "repairs"):
                incoming = _number(record[field], int if field in {"bedrooms", "sqft"} else float)
                if getattr(prop, field) in (None, 0) and incoming is not None:
                    setattr(prop, field, incoming)
                    changed[field] = incoming
            merged_signals = list(dict.fromkeys((prop.distress_signals or []) + record["distress_signals"]))
            if merged_signals != (prop.distress_signals or []):
                prop.distress_signals = merged_signals
                changed["distress_signals"] = merged_signals
            if changed:
                updated += 1
                status = "updated"
            else:
                duplicate += 1
                status = "duplicate"
            db.add(CrmActivity(
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                lead_id=lead.id,
                activity_type="lead_import_reconciled",
                summary=f"{source.title()} import reconciled with existing lead",
                metadata_json={"batch_id": batch.id, "external_id": record["external_id"], "changes": changed},
            ))
            results.append({"row": index, "status": status, "lead_id": lead.id, "property_id": prop.id, "changes": changed})
            continue

        lead = Lead(
            seller_name="Unverified owner" if review_only else record["seller_name"],
            phone="unknown" if review_only else record["phone"] or "unknown",
            email=None if review_only else record["email"], source=record["source"],
            status="property_candidate" if review_only else "new",
            notes=(
                f"Autonomously discovered through acquisition intake batch #{batch.id}. "
                "Ownership, contact consent, and outreach eligibility are not verified."
                if review_only else f"Imported through acquisition intake batch #{batch.id}"
            ),
        )
        prop = Property(
            lead=lead, address=record["address"], city=record["city"], state=record["state"],
            zip_code=record["zip_code"], property_type=record["property_type"],
            bedrooms=_number(record["bedrooms"], int), bathrooms=_number(record["bathrooms"]),
            sqft=_number(record["sqft"], int), asking_price=_number(record["asking_price"]),
            arv=_number(record["arv"]), repairs=_number(record["repairs"]),
            distress_signals=record["distress_signals"],
        )
        db.add(lead)
        db.flush()
        db.add(prop)
        db.flush()
        db.add_all([
            WorkspaceEntity(organization_id=principal.organization_id, entity_type="lead", entity_id=lead.id),
            WorkspaceEntity(organization_id=principal.organization_id, entity_type="property", entity_id=prop.id),
            CrmActivity(
                organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id,
                activity_type="lead_imported", summary=f"Lead imported from {source}",
                metadata_json={"batch_id": batch.id, "external_id": record["external_id"]},
            ),
        ])
        event = emit_event(
            db, principal.organization_id,
            "PropertyCandidateDiscovered" if review_only else "LeadCreated",
            "property" if review_only else "lead",
            prop.id if review_only else lead.id,
            payload={
                "lead_id": lead.id, "property_id": prop.id, "source": source,
                "batch_id": batch.id, "review_only": review_only,
                "outreach_allowed": False if review_only else None,
            },
            source="autonomous_property_acquisition" if review_only else "acquisition_intake",
            event_key=f"acquisition:{principal.organization_id}:{source}:{record['external_id'] or key}",
        )
        created += 1
        existing[key] = (lead, prop)
        results.append({"row": index, "status": "created", "lead_id": lead.id, "property_id": prop.id, "event_id": event.id})

    batch.records_created = created
    batch.records_updated = updated
    batch.records_duplicate = duplicate
    batch.records_rejected = rejected
    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc)
    batch.result_json = {"rows": results[:250], "truncated": len(results) > 250}
    db.commit()
    return {
        "batch_id": batch.id, "source": source, "received": len(records),
        "created": created, "updated": updated, "duplicate": duplicate,
        "rejected": rejected, "results": results,
        "review_only": review_only,
    }

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .acquisition_intake_models import AcquisitionImportBatch
from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .background_jobs import BackgroundJob
from .database import get_db
from .event_bus import emit_event
from .models import Deal, Lead, OpsTask, Property

router = APIRouter(prefix="/acquisition-intake", tags=["autonomous acquisition intake"])

ALLOWED_SOURCES = {
    "propstream", "batchdata", "attom", "county", "mls", "fsbo",
    "facebook", "driving_for_dollars", "csv", "manual", "public_address_paste", "other",
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
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
        "distress_signals": list(dict.fromkeys(distress if isinstance(distress, list) else [])),
        "external_id": _clean(record.get("external_id") or record.get("record_id") or record.get("property_id")),
        "raw": record,
    }


def parse_pasted_addresses(text: str) -> tuple[list[dict], list[dict]]:
    """Parse address CSV with optional asking price and source URL."""
    records: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    rows = csv.reader(io.StringIO(str(text or "")))
    for line_number, row in enumerate(rows, 1):
        values = [_clean(value) for value in row]
        if not any(values):
            continue
        if line_number == 1 and {value.lower() for value in values} >= {"address", "city", "state"}:
            continue
        if len(values) >= 4:
            address, city, state, zip_code = values[:4]
            asking_price = values[4] if len(values) > 4 else ""
            source_url = values[5] if len(values) > 5 else ""
        elif len(values) == 3:
            match = re.fullmatch(r"([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)", values[2])
            if not match:
                rejected.append({"line": line_number, "input": ", ".join(values), "reason": "expected_state_zip"})
                continue
            address, city = values[:2]
            state, zip_code = match.groups()
            asking_price = source_url = ""
        else:
            raw = values[0] if values else ""
            match = re.match(r"^(.+?),\s*([^,]+?),\s*([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)$", raw)
            if not match:
                rejected.append({"line": line_number, "input": raw, "reason": "expected_street_city_state_zip"})
                continue
            address, city, state, zip_code = match.groups()
            asking_price = source_url = ""
        state = state.upper()
        if not address or not city or not re.fullmatch(r"[A-Z]{2}", state) or not re.fullmatch(r"\d{5}(?:-\d{4})?", zip_code):
            rejected.append({"line": line_number, "input": ", ".join(values), "reason": "invalid_address_components"})
            continue
        key = _address_key(address, city, state, zip_code)
        if key in seen:
            rejected.append({"line": line_number, "input": ", ".join(values), "reason": "duplicate_in_paste"})
            continue
        seen.add(key)
        record = {
            "address": address, "city": city, "state": state, "zip_code": zip_code,
            "source": "public_address_paste",
        }
        if asking_price:
            normalized_price = re.sub(r"[$,\s]", "", asking_price)
            try:
                record["asking_price"] = float(normalized_price)
            except ValueError:
                rejected.append({"line": line_number, "input": asking_price, "reason": "invalid_asking_price"})
                continue
        if source_url:
            record["external_id"] = source_url
        records.append(record)
    return records, rejected


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
    candidate_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    candidates = db.scalars(select(Lead).where(
        Lead.id.in_(candidate_ids),
        Lead.status == "property_candidate",
    ).order_by(Lead.created_at.desc()).limit(100)).all() if candidate_ids else []
    return {
        "counts": totals,
        "autonomous_feed": acquisition_feed_status(),
        "candidates": [{
            "lead_id": lead.id,
            "property_id": lead.property.id if lead.property else None,
            "address": lead.property.address if lead.property else None,
            "city": lead.property.city if lead.property else None,
            "state": lead.property.state if lead.property else None,
            "zip_code": lead.property.zip_code if lead.property else None,
            "source": lead.source,
            "asking_price": lead.property.asking_price if lead.property else None,
            "created_at": lead.created_at,
        } for lead in candidates],
        "batches": [{
            "id": row.id, "source": row.source, "status": row.status,
            "records_received": row.records_received, "records_created": row.records_created,
            "records_updated": row.records_updated, "records_duplicate": row.records_duplicate,
            "records_rejected": row.records_rejected, "result": row.result_json,
            "created_at": row.created_at, "completed_at": row.completed_at,
        } for row in batches],
    }


@router.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    linked = db.scalar(select(WorkspaceEntity).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    lead = db.get(Lead, lead_id)
    if not linked or not lead:
        raise HTTPException(404, "Lead not found in this workspace")
    active_deal = db.scalar(select(Deal).join(Property, Deal.property_id == Property.id).where(
        Property.lead_id == lead_id,
        Deal.stage.not_in(["closed", "dead"]),
    ))
    if active_deal:
        raise HTTPException(409, f"Lead has active deal #{active_deal.id}; close or mark the deal dead before deletion")
    reason = _clean((payload or {}).get("reason") or "Removed by workspace manager")
    property_id = lead.property.id if lead.property else None
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="lead_deleted",
        summary=f"Lead #{lead.id} removed from active workspace",
        metadata_json={"lead_id": lead.id, "property_id": property_id, "reason": reason, "deletion_mode": "soft_delete_pii_suppressed"},
    ))
    lead.status = "deleted"
    lead.seller_name = "Deleted lead"
    lead.phone = "deleted"
    lead.email = None
    lead.notes = f"Soft deleted at {datetime.now(timezone.utc).isoformat()}. Reason: {reason}"
    for task in db.scalars(select(OpsTask).where(OpsTask.lead_id == lead_id, OpsTask.status.in_(["queued", "pending"]))).all():
        task.status = "cancelled"
    for follow_up in db.scalars(select(FollowUpTask).where(
        FollowUpTask.organization_id == principal.organization_id,
        FollowUpTask.lead_id == lead_id,
        FollowUpTask.status.in_(["open", "pending"]),
    )).all():
        follow_up.status = "cancelled"
    for job in db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == principal.organization_id,
        BackgroundJob.job_type == "acquisition_lead",
        BackgroundJob.status.in_(["queued", "retry"]),
    )).all():
        if int((job.payload_json or {}).get("lead_id") or 0) == lead_id:
            job.status = "cancelled"
            job.completed_at = datetime.now(timezone.utc)
    db.query(WorkspaceEntity).filter(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ).delete(synchronize_session=False)
    if property_id:
        db.query(WorkspaceEntity).filter(
            WorkspaceEntity.organization_id == principal.organization_id,
            WorkspaceEntity.entity_type == "property",
            WorkspaceEntity.entity_id == property_id,
        ).delete(synchronize_session=False)
    db.commit()
    return {
        "lead_id": lead_id,
        "property_id": property_id,
        "status": "deleted",
        "recoverable_from_audit": False,
        "audit_retained": True,
        "contact_data_removed": True,
        "reason": reason,
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
        if record["state"] == "TX" and not review_only:
            rejected += 1
            results.append({"row": index, "status": "rejected", "reason": "texas_requires_review_only_discovery"})
            continue

        key = _address_key(record["address"], record["city"], record["state"], record["zip_code"])
        match = existing.get(key)
        if match:
            lead, prop = match
            changed = {}
            if not review_only and not lead.phone and record["phone"]:
                lead.phone = record["phone"]
                changed["phone"] = record["phone"]
            if not review_only and not lead.email and record["email"]:
                lead.email = record["email"]
                changed["email"] = record["email"]
            for field in ("bedrooms", "bathrooms", "sqft", "asking_price", "arv", "repairs", "latitude", "longitude"):
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
                f"Ownership, contact consent, outreach eligibility, and jurisdictional compliance are not verified. "
                f"{'Texas candidate: review-only until jurisdiction policy clears outreach/offer execution.' if record['state'] == 'TX' else ''}"
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
            latitude=_number(record["latitude"]), longitude=_number(record["longitude"]),
        )
        db.add(lead)
        db.flush()
        db.add(prop)
        db.flush()
        db.add_all([
            WorkspaceEntity(organization_id=principal.organization_id, entity_type="lead", entity_id=lead.id),
            WorkspaceEntity(organization_id=principal.organization_id, entity_type="property", entity_id=prop.id),
            CrmActivity(
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                lead_id=lead.id,
                activity_type="property_candidate_discovered" if review_only else "lead_imported",
                summary=(
                    f"Review-only property candidate discovered from {source}"
                    if review_only else f"Lead imported from {source}"
                ),
                metadata_json={
                    "batch_id": batch.id,
                    "property_id": prop.id,
                    "external_id": record["external_id"],
                    "source": source,
                    "review_only": review_only,
                    "texas_review_only": bool(review_only and record["state"] == "TX"),
                    "outreach_allowed": False if review_only else None,
                },
            ),
        ])
        emit_event(db, principal.organization_id, "PropertyCandidateDiscovered" if review_only else "LeadImported", {
            "lead_id": lead.id,
            "property_id": prop.id,
            "source": source,
            "review_only": review_only,
            "state": record["state"],
            "texas_review_only": bool(review_only and record["state"] == "TX"),
        })
        existing[key] = (lead, prop)
        created += 1
        results.append({"row": index, "status": "created", "lead_id": lead.id, "property_id": prop.id})

    batch.records_created = created
    batch.records_updated = updated
    batch.records_duplicate = duplicate
    batch.records_rejected = rejected
    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc)
    batch.result_json = {"results": results[:1000]}
    db.commit()
    return {
        "batch_id": batch.id,
        "source": source,
        "status": "completed",
        "received": len(records),
        "created": created,
        "updated": updated,
        "duplicate": duplicate,
        "rejected": rejected,
    }

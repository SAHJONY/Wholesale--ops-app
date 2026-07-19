from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead, Property

router = APIRouter(prefix="/data-intake", tags=["production data intake"])
REQUIRED_COLUMNS = {"seller_name", "phone", "address", "city", "state", "zip_code"}
OPTIONAL_COLUMNS = {"email", "source", "notes", "asking_price", "arv", "repairs", "bedrooms", "bathrooms", "sqft", "motivation_score", "distress_score", "equity_score"}
MAX_ROWS = 5000


def _text(value: object) -> str:
    return str(value or "").strip()


def _phone(value: object) -> str:
    return re.sub(r"\D", "", _text(value))[-10:]


def _address_key(row: dict) -> str:
    return "|".join([re.sub(r"\s+", " ", _text(row.get("address")).lower()), _text(row.get("city")).lower(), _text(row.get("state")).upper(), _text(row.get("zip_code"))[:5]])


def _number(value: object, kind=float):
    raw = _text(value).replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        return kind(float(raw))
    except (TypeError, ValueError):
        return None


def _parse(csv_text: str) -> tuple[list[dict], list[str]]:
    if not csv_text.strip():
        raise HTTPException(422, "CSV content is empty")
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = {str(name or "").strip().lower() for name in (reader.fieldnames or [])}
    missing = sorted(REQUIRED_COLUMNS - headers)
    if missing:
        raise HTTPException(422, f"Missing required columns: {', '.join(missing)}")
    rows = []
    for index, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            raise HTTPException(413, f"CSV exceeds {MAX_ROWS} row limit")
        normalized = {str(key or "").strip().lower(): value for key, value in raw.items()}
        normalized["row_number"] = index
        rows.append(normalized)
    return rows, sorted(headers)


def _existing_keys(db: Session, organization_id: int) -> tuple[set[str], set[str]]:
    lead_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(WorkspaceEntity.organization_id == organization_id, WorkspaceEntity.entity_type == "lead")).all())
    if not lead_ids:
        return set(), set()
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()
    properties = db.scalars(select(Property).where(Property.lead_id.in_(lead_ids))).all()
    return ({_phone(lead.phone) for lead in leads if _phone(lead.phone)}, {_address_key({"address": p.address, "city": p.city, "state": p.state, "zip_code": p.zip_code}) for p in properties})


def _preview_rows(db: Session, principal: Principal, csv_text: str) -> dict:
    rows, headers = _parse(csv_text)
    existing_phones, existing_addresses = _existing_keys(db, principal.organization_id)
    seen_phones: set[str] = set(); seen_addresses: set[str] = set()
    accepted, duplicates, rejected = [], [], []
    for row in rows:
        phone = _phone(row.get("phone")); state = _text(row.get("state")).upper(); address_key = _address_key(row)
        errors = []
        if state == "TX": errors.append("Texas is excluded from acquisition workflows")
        if not phone: errors.append("Valid phone is required")
        if not all(_text(row.get(name)) for name in ["seller_name", "address", "city", "state", "zip_code"]): errors.append("Required identity or property fields are missing")
        duplicate_reason = None
        if phone and (phone in existing_phones or phone in seen_phones): duplicate_reason = "duplicate_phone"
        if address_key in existing_addresses or address_key in seen_addresses: duplicate_reason = duplicate_reason or "duplicate_property"
        item = {"row_number": row["row_number"], "seller_name": _text(row.get("seller_name")), "address": _text(row.get("address")), "city": _text(row.get("city")), "state": state, "zip_code": _text(row.get("zip_code")), "phone_last4": phone[-4:] if phone else "", "source": _text(row.get("source")) or "csv_import"}
        if errors:
            item["errors"] = errors; rejected.append(item); continue
        if duplicate_reason:
            item["reason"] = duplicate_reason; duplicates.append(item); continue
        accepted.append(item); seen_phones.add(phone); seen_addresses.add(address_key)
    return {"generated_at": datetime.utcnow(), "headers": headers, "total_rows": len(rows), "accepted_count": len(accepted), "duplicate_count": len(duplicates), "rejected_count": len(rejected), "accepted_row_numbers": [item["row_number"] for item in accepted], "accepted": accepted[:100], "duplicates": duplicates[:100], "rejected": rejected[:100]}


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    imports = db.scalars(select(CrmActivity).where(CrmActivity.organization_id == principal.organization_id, CrmActivity.activity_type == "data_intake_import").order_by(CrmActivity.created_at.desc()).limit(25)).all()
    return {"generated_at": datetime.utcnow(), "required_columns": sorted(REQUIRED_COLUMNS), "optional_columns": sorted(OPTIONAL_COLUMNS), "max_rows": MAX_ROWS, "texas_excluded": True, "imports": [{"id": item.id, "summary": item.summary, "metadata": item.metadata_json, "created_at": item.created_at} for item in imports]}


@router.post("/preview")
def preview(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return _preview_rows(db, principal, str(payload.get("csv_text") or ""))


@router.post("/commit")
def commit(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    csv_text = str(payload.get("csv_text") or ""); source_label = _text(payload.get("source_label")) or "csv_import"
    preview_result = _preview_rows(db, principal, csv_text)
    accepted_rows = set(preview_result["accepted_row_numbers"])
    rows, _ = _parse(csv_text); created = []
    for row in rows:
        if row["row_number"] not in accepted_rows: continue
        lead = Lead(seller_name=_text(row.get("seller_name")), phone=_phone(row.get("phone")), email=_text(row.get("email")) or None, source=source_label, notes=_text(row.get("notes")) or None, motivation_score=_number(row.get("motivation_score")) or 0, distress_score=_number(row.get("distress_score")) or 0, equity_score=_number(row.get("equity_score")) or 0)
        property_row = Property(address=_text(row.get("address")), city=_text(row.get("city")), state=_text(row.get("state")).upper(), zip_code=_text(row.get("zip_code")), asking_price=_number(row.get("asking_price")), arv=_number(row.get("arv")), repairs=_number(row.get("repairs")), bedrooms=_number(row.get("bedrooms"), int), bathrooms=_number(row.get("bathrooms")), sqft=_number(row.get("sqft"), int))
        lead.property = property_row; db.add(lead); db.flush()
        db.add_all([WorkspaceEntity(organization_id=principal.organization_id, entity_type="lead", entity_id=lead.id), WorkspaceEntity(organization_id=principal.organization_id, entity_type="property", entity_id=property_row.id)])
        created.append({"lead_id": lead.id, "property_id": property_row.id})
    db.add(CrmActivity(organization_id=principal.organization_id, user_id=principal.user_id, activity_type="data_intake_import", summary=f"Imported {len(created)} production lead(s) from {source_label}", metadata_json={"source_label": source_label, "total_rows": preview_result["total_rows"], "created": len(created), "duplicates": preview_result["duplicate_count"], "rejected": preview_result["rejected_count"], "texas_excluded": True}))
    db.commit()
    preview_result.pop("accepted_row_numbers", None)
    return {"created_count": len(created), "records": created, "preview": preview_result}

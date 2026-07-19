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
from .models import Buyer

router = APIRouter(prefix="/buyer-intake", tags=["production buyer intake"])

REQUIRED_COLUMNS = {"name", "phone", "zip_codes"}
OPTIONAL_COLUMNS = {
    "email", "company", "buyer_type", "asset_types", "min_price", "max_price",
    "max_rehab", "closing_days", "proof_of_funds_verified", "reliability_score",
    "response_rate", "source",
}
MAX_ROWS = 5000


def _text(value: object) -> str:
    return str(value or "").strip()


def _phone(value: object) -> str:
    return re.sub(r"\D", "", _text(value))[-10:]


def _number(value: object, kind=float, default=None):
    raw = _text(value).replace("$", "").replace(",", "")
    if not raw:
        return default
    try:
        return kind(float(raw))
    except (TypeError, ValueError):
        return default


def _boolean(value: object) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y", "verified"}


def _list(value: object) -> list[str]:
    return [item.strip() for item in re.split(r"[|;,]", _text(value)) if item.strip()]


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
        row = {str(key or "").strip().lower(): value for key, value in raw.items()}
        row["row_number"] = index
        rows.append(row)
    return rows, sorted(headers)


def _existing(db: Session, organization_id: int) -> tuple[set[str], set[str]]:
    buyer_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "buyer",
    )).all())
    if not buyer_ids:
        return set(), set()
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all()
    phones = {_phone(item.phone) for item in buyers if _phone(item.phone)}
    emails = {_text(item.email).lower() for item in buyers if _text(item.email)}
    return phones, emails


def _classify(db: Session, principal: Principal, csv_text: str) -> tuple[dict, set[int]]:
    rows, headers = _parse(csv_text)
    existing_phones, existing_emails = _existing(db, principal.organization_id)
    seen_phones: set[str] = set()
    seen_emails: set[str] = set()
    accepted, duplicates, rejected = [], [], []
    accepted_numbers: set[int] = set()

    for row in rows:
        phone = _phone(row.get("phone"))
        email = _text(row.get("email")).lower()
        zips = _list(row.get("zip_codes"))
        asset_types = _list(row.get("asset_types")) or ["single_family"]
        errors = []
        if not _text(row.get("name")):
            errors.append("Buyer name is required")
        if not phone:
            errors.append("Valid phone is required")
        if not zips:
            errors.append("At least one ZIP code is required")
        if any(item.upper() == "TX" or item.lower().startswith("texas") for item in zips):
            errors.append("Texas is excluded from wholesale workflows")
        min_price = _number(row.get("min_price"), default=0) or 0
        max_price = _number(row.get("max_price"), default=10_000_000) or 10_000_000
        if max_price < min_price:
            errors.append("max_price must be greater than or equal to min_price")
        duplicate_reason = None
        if phone and (phone in existing_phones or phone in seen_phones):
            duplicate_reason = "duplicate_phone"
        if email and (email in existing_emails or email in seen_emails):
            duplicate_reason = duplicate_reason or "duplicate_email"
        item = {
            "row_number": row["row_number"],
            "name": _text(row.get("name")),
            "company": _text(row.get("company")),
            "phone_last4": phone[-4:] if phone else "",
            "email": email,
            "zip_codes": zips,
            "asset_types": asset_types,
            "proof_of_funds_verified": _boolean(row.get("proof_of_funds_verified")),
        }
        if errors:
            item["errors"] = errors
            rejected.append(item)
            continue
        if duplicate_reason:
            item["reason"] = duplicate_reason
            duplicates.append(item)
            continue
        accepted.append(item)
        accepted_numbers.add(row["row_number"])
        seen_phones.add(phone)
        if email:
            seen_emails.add(email)

    result = {
        "generated_at": datetime.utcnow(),
        "headers": headers,
        "total_rows": len(rows),
        "accepted_count": len(accepted),
        "duplicate_count": len(duplicates),
        "rejected_count": len(rejected),
        "verified_pof_count": sum(1 for item in accepted if item["proof_of_funds_verified"]),
        "accepted": accepted[:100],
        "duplicates": duplicates[:100],
        "rejected": rejected[:100],
    }
    return result, accepted_numbers


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    imports = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.activity_type == "buyer_intake_import",
    ).order_by(CrmActivity.created_at.desc()).limit(25)).all()
    return {
        "generated_at": datetime.utcnow(),
        "required_columns": sorted(REQUIRED_COLUMNS),
        "optional_columns": sorted(OPTIONAL_COLUMNS),
        "max_rows": MAX_ROWS,
        "texas_excluded": True,
        "imports": [{"id": item.id, "summary": item.summary, "metadata": item.metadata_json, "created_at": item.created_at} for item in imports],
    }


@router.post("/preview")
def preview(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    result, _ = _classify(db, principal, str(payload.get("csv_text") or ""))
    return result


@router.post("/commit")
def commit(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    csv_text = str(payload.get("csv_text") or "")
    source_label = _text(payload.get("source_label")) or "buyer_csv_import"
    preview_result, accepted_numbers = _classify(db, principal, csv_text)
    rows, _ = _parse(csv_text)
    created = []
    for row in rows:
        if row["row_number"] not in accepted_numbers:
            continue
        buyer = Buyer(
            name=_text(row.get("name")),
            company=_text(row.get("company")) or None,
            buyer_type=_text(row.get("buyer_type")) or "cash_buyer",
            phone=_phone(row.get("phone")),
            email=_text(row.get("email")) or None,
            zip_codes=_list(row.get("zip_codes")),
            asset_types=_list(row.get("asset_types")) or ["single_family"],
            min_price=_number(row.get("min_price"), default=0) or 0,
            max_price=_number(row.get("max_price"), default=10_000_000) or 10_000_000,
            max_rehab=_number(row.get("max_rehab"), default=500_000) or 500_000,
            closing_days=max(1, _number(row.get("closing_days"), int, 14) or 14),
            proof_of_funds_verified=_boolean(row.get("proof_of_funds_verified")),
            reliability_score=max(0, min(100, _number(row.get("reliability_score"), default=50) or 50)),
            response_rate=max(0, min(100, _number(row.get("response_rate"), default=0) or 0)),
        )
        db.add(buyer)
        db.flush()
        db.add(WorkspaceEntity(organization_id=principal.organization_id, entity_type="buyer", entity_id=buyer.id))
        created.append({"buyer_id": buyer.id, "proof_of_funds_verified": buyer.proof_of_funds_verified})

    audit = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="buyer_intake_import",
        summary=f"Imported {len(created)} buyer(s) from {source_label}",
        metadata_json={
            "source_label": source_label,
            "total_rows": preview_result["total_rows"],
            "created": len(created),
            "duplicates": preview_result["duplicate_count"],
            "rejected": preview_result["rejected_count"],
            "proof_of_funds_verified": sum(1 for item in created if item["proof_of_funds_verified"]),
            "texas_excluded": True,
        },
    )
    db.add(audit)
    db.commit()
    return {"created_count": len(created), "records": created, "preview": preview_result}

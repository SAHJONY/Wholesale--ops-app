from __future__ import annotations

import re
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .database import get_db

router = APIRouter(prefix="/joint-ventures", tags=["joint ventures"])

JV_ACTIVITY_TYPE = "public_partner_intake"
JV_ROLE = "wholesaler_jv"
JV_STAGES = {
    "submitted",
    "reviewing",
    "qualified",
    "jv_signed",
    "marketing",
    "buyer_identified",
    "under_contract",
    "closed",
    "dead",
}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    raw = re.sub(r"[^0-9.\-]", "", str(value))
    if not raw or raw in {"-", ".", "-."}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _message_value(message: str, label: str) -> str | None:
    match = re.search(rf"(?:^|\n){re.escape(label)}:\s*([^\n]+)", message or "", flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _split_percent(value: Any) -> float | None:
    """Return SAHJONY's percentage of the assignment fee.

    Structured intake should supply sahjony_split_percent. Legacy free-text values
    such as 50/50 are interpreted as equal first/second shares only when explicit.
    Ambiguous text is left unscored rather than guessed.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value)))
    raw = str(value).strip().lower().replace("%", "")
    direct = _number(raw)
    if direct is not None and "/" not in raw:
        return max(0.0, min(100.0, direct))
    pair = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*", raw)
    if pair:
        left, right = float(pair.group(1)), float(pair.group(2))
        total = left + right
        return round(left / total * 100, 2) if total > 0 else None
    return None


def _jv_rows(db: Session, organization_id: int) -> list[CrmActivity]:
    rows = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == organization_id,
        CrmActivity.activity_type == JV_ACTIVITY_TYPE,
    ).order_by(CrmActivity.created_at.desc())).all()
    return [row for row in rows if str((row.metadata_json or {}).get("role") or "") == JV_ROLE]


def _normalize(row: CrmActivity) -> dict[str, Any]:
    meta = dict(row.metadata_json or {})
    message = str(meta.get("message") or "")
    contract_price = _number(meta.get("contract_price"))
    if contract_price is None:
        contract_price = _number(_message_value(message, "Seller/contract price"))
    buyer_price = _number(meta.get("buyer_price"))
    arv = _number(meta.get("arv"))
    if arv is None:
        arv = _number(_message_value(message, "ARV"))
    repairs = _number(meta.get("repairs"))
    if repairs is None:
        repairs = _number(_message_value(message, "Repairs"))

    split = _split_percent(meta.get("sahjony_split_percent"))
    if split is None:
        split = _split_percent(meta.get("jv_split"))
    if split is None:
        split = _split_percent(_message_value(message, "Desired JV split"))

    stage = str(meta.get("jv_stage") or "submitted").strip().lower()
    if stage not in JV_STAGES:
        stage = "submitted"

    gross_fee = None
    if buyer_price is not None and contract_price is not None:
        gross_fee = round(max(0.0, buyer_price - contract_price), 2)
    sahjony_revenue = round(gross_fee * split / 100, 2) if gross_fee is not None and split is not None else None
    partner_revenue = round(gross_fee - sahjony_revenue, 2) if gross_fee is not None and sahjony_revenue is not None else None

    buyer_identified_at = _dt(meta.get("buyer_identified_at"))
    closed_at = _dt(meta.get("closed_at"))
    created_at = row.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    days_to_buyer = None
    if created_at and buyer_identified_at and buyer_identified_at >= created_at:
        days_to_buyer = round((buyer_identified_at - created_at).total_seconds() / 86400, 2)

    return {
        "id": row.id,
        "name": meta.get("name"),
        "company": meta.get("company"),
        "email": meta.get("email"),
        "phone": meta.get("phone"),
        "property_address": meta.get("property_address") or _message_value(message, "Property"),
        "city": meta.get("city"),
        "state": meta.get("state"),
        "zip_code": meta.get("zip_code"),
        "contract_status": meta.get("contract_status") or _message_value(message, "Contract status"),
        "contract_price": contract_price,
        "buyer_price": buyer_price,
        "arv": arv,
        "repairs": repairs,
        "sahjony_split_percent": split,
        "stage": stage,
        "buyer_status": meta.get("buyer_status") or _message_value(message, "Buyer status"),
        "gross_assignment_fee": gross_fee,
        "sahjony_revenue": sahjony_revenue,
        "partner_revenue": partner_revenue,
        "buyer_identified_at": buyer_identified_at,
        "closed_at": closed_at,
        "days_to_buyer": days_to_buyer,
        "created_at": created_at,
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    closed = [row for row in rows if row["stage"] == "closed"]
    converted = len(closed)
    projected_fees = [row["gross_assignment_fee"] for row in rows if row["gross_assignment_fee"] is not None and row["stage"] != "dead"]
    realized_fees = [row["gross_assignment_fee"] for row in closed if row["gross_assignment_fee"] is not None]
    realized_sahjony = [row["sahjony_revenue"] for row in closed if row["sahjony_revenue"] is not None]
    projected_sahjony = [row["sahjony_revenue"] for row in rows if row["sahjony_revenue"] is not None and row["stage"] != "dead"]
    splits = [row["sahjony_split_percent"] for row in rows if row["sahjony_split_percent"] is not None and row["stage"] != "dead"]
    days = [row["days_to_buyer"] for row in rows if row["days_to_buyer"] is not None]

    return {
        "submissions": total,
        "closed_jvs": converted,
        "conversion_rate_percent": round(converted / total * 100, 2) if total else 0.0,
        "projected_gross_assignment_revenue": round(sum(projected_fees), 2),
        "jv_gross_assignment_revenue": round(sum(realized_fees), 2),
        "projected_sahjony_revenue": round(sum(projected_sahjony), 2),
        "realized_sahjony_revenue": round(sum(realized_sahjony), 2),
        "average_sahjony_split_percent": round(mean(splits), 2) if splits else None,
        "average_days_to_buyer": round(mean(days), 2) if days else None,
        "deals_with_buyer": len(days),
        "definitions": {
            "assignment_fee": "buyer_price - contract_price; floored at zero",
            "jv_gross_assignment_revenue": "sum of gross assignment fees for closed JV deals",
            "average_split": "mean SAHJONY split percentage across active/non-dead JV deals with a documented split",
            "conversion_rate": "closed JV deals divided by all JV submissions",
            "days_to_buyer": "elapsed calendar days from JV submission to first documented buyer identification",
        },
    }


@router.get("")
def list_joint_ventures(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = [_normalize(row) for row in _jv_rows(db, principal.organization_id)]
    return {"metrics": _metrics(rows), "joint_ventures": rows}


@router.get("/metrics")
def joint_venture_metrics(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = [_normalize(row) for row in _jv_rows(db, principal.organization_id)]
    return _metrics(rows)


@router.post("/assignment-fee")
def assignment_fee(payload: dict[str, Any], principal: Principal = Depends(get_principal)):
    contract_price = _number(payload.get("contract_price"))
    buyer_price = _number(payload.get("buyer_price"))
    split = _split_percent(payload.get("sahjony_split_percent"))
    if contract_price is None or buyer_price is None:
        raise HTTPException(422, "contract_price and buyer_price are required")
    gross = round(max(0.0, buyer_price - contract_price), 2)
    sahjony = round(gross * split / 100, 2) if split is not None else None
    return {
        "contract_price": contract_price,
        "buyer_price": buyer_price,
        "gross_assignment_fee": gross,
        "sahjony_split_percent": split,
        "sahjony_revenue": sahjony,
        "partner_revenue": round(gross - sahjony, 2) if sahjony is not None else None,
        "assignment_margin_on_buyer_price_percent": round(gross / buyer_price * 100, 2) if buyer_price > 0 else None,
    }


@router.patch("/{activity_id}")
def update_joint_venture(
    activity_id: int,
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    row = db.get(CrmActivity, activity_id)
    if not row or row.organization_id != principal.organization_id or row.activity_type != JV_ACTIVITY_TYPE:
        raise HTTPException(404, "JV record not found")
    meta = dict(row.metadata_json or {})
    if str(meta.get("role") or "") != JV_ROLE:
        raise HTTPException(404, "JV record not found")

    allowed = {
        "contract_price", "buyer_price", "arv", "repairs", "sahjony_split_percent",
        "jv_stage", "buyer_status", "buyer_identified_at", "closed_at", "notes_internal",
    }
    for key in allowed:
        if key in payload:
            meta[key] = payload[key]

    stage = str(meta.get("jv_stage") or "submitted").strip().lower()
    if stage not in JV_STAGES:
        raise HTTPException(422, f"Invalid jv_stage. Valid: {', '.join(sorted(JV_STAGES))}")
    if stage in {"buyer_identified", "under_contract", "closed"} and not meta.get("buyer_identified_at"):
        meta["buyer_identified_at"] = datetime.now(timezone.utc).isoformat()
    if stage == "closed" and not meta.get("closed_at"):
        meta["closed_at"] = datetime.now(timezone.utc).isoformat()

    row.metadata_json = meta
    db.add(row)
    db.commit()
    db.refresh(row)
    return _normalize(row)

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import AppUser, CrmActivity
from .database import get_db

router = APIRouter(prefix="/audit", tags=["audit and accountability"])

SENSITIVE_METADATA_KEYS = {
    "access_token", "api_key", "authorization", "bootstrap_secret", "code",
    "database_url", "password", "secret", "smtp_pass", "token",
}


def _sanitize(value):
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_METADATA_KEYS else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _category(activity_type: str) -> str:
    value = activity_type.lower()
    if any(term in value for term in ("login", "password", "session", "security", "key_")):
        return "security"
    if any(term in value for term in ("approval", "offer", "contract", "signature")):
        return "approval"
    if any(term in value for term in ("scheduled", "agent", "automation", "job", "event")):
        return "automation"
    if any(term in value for term in ("closing", "title", "funding", "earnest")):
        return "closing"
    if any(term in value for term in ("lead", "buyer", "property", "county", "enrichment")):
        return "data"
    return "operations"


def _query(db: Session, organization_id: int, days: int, category: str | None, activity_type: str | None):
    cutoff = datetime.utcnow() - timedelta(days=days)
    statement = (
        select(CrmActivity, AppUser)
        .outerjoin(AppUser, AppUser.id == CrmActivity.user_id)
        .where(
            CrmActivity.organization_id == organization_id,
            CrmActivity.created_at >= cutoff,
        )
        .order_by(CrmActivity.created_at.desc())
    )
    if activity_type:
        statement = statement.where(CrmActivity.activity_type == activity_type)
    rows = db.execute(statement.limit(1000)).all()
    if category:
        rows = [row for row in rows if _category(row[0].activity_type) == category]
    return rows


def _serialize(activity: CrmActivity, user: AppUser | None) -> dict:
    return {
        "id": activity.id,
        "category": _category(activity.activity_type),
        "activity_type": activity.activity_type,
        "summary": activity.summary,
        "user": None if not user else {"id": user.id, "name": user.name, "email": user.email},
        "lead_id": activity.lead_id,
        "deal_id": activity.deal_id,
        "metadata": _sanitize(activity.metadata_json or {}),
        "created_at": activity.created_at,
    }


@router.get("/snapshot")
def snapshot(
    days: int = Query(default=30, ge=1, le=365),
    category: str | None = Query(default=None),
    activity_type: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    rows = _query(db, principal.organization_id, days, category, activity_type)
    items = [_serialize(activity, user) for activity, user in rows]
    category_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for item in items:
        category_counts[item["category"]] = category_counts.get(item["category"], 0) + 1
        type_counts[item["activity_type"]] = type_counts.get(item["activity_type"], 0) + 1
    return {
        "generated_at": datetime.utcnow(),
        "window_days": days,
        "total": len(items),
        "category_counts": category_counts,
        "activity_type_counts": type_counts,
        "items": items[:250],
        "retention_note": "Audit view uses the existing tenant-scoped CRM activity ledger.",
    }


@router.get("/export.csv")
def export_csv(
    days: int = Query(default=30, ge=1, le=365),
    category: str | None = Query(default=None),
    activity_type: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    rows = _query(db, principal.organization_id, days, category, activity_type)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "category", "activity_type", "summary", "user_email", "lead_id", "deal_id"])
    for activity, user in rows:
        writer.writerow([
            activity.id,
            activity.created_at.isoformat(),
            _category(activity.activity_type),
            activity.activity_type,
            activity.summary,
            user.email if user else "",
            activity.lead_id or "",
            activity.deal_id or "",
        ])
    filename = f"sahjony-audit-{datetime.utcnow().date().isoformat()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

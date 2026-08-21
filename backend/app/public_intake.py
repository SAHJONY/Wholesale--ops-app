from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth_models import CrmActivity, FollowUpTask, Organization, WorkspaceEntity
from .database import get_db
from .models import Buyer, Lead, Property

router = APIRouter(prefix="/public-intake", tags=["public deal flow"])

KINDS = {"seller", "buyer", "partner", "contact"}


def _text(value: object, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _email(value: object) -> str | None:
    email = _text(value, 255).lower()
    if not email:
        return None
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Valid email is required")
    return email


def _phone(value: object) -> str:
    phone = re.sub(r"[^0-9+]", "", _text(value, 40))
    if len(re.sub(r"\D", "", phone)) < 10:
        raise HTTPException(422, "Valid phone is required")
    return phone


def _number(value: object, default=None):
    raw = _text(value, 40).replace("$", "").replace(",", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise HTTPException(422, "Invalid numeric value") from exc


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[|,;]", _text(value, 1000))
    return [str(item).strip()[:80] for item in raw if str(item).strip()]


def _workspace(db: Session) -> Organization:
    configured = _text(os.getenv("PUBLIC_INTAKE_ORGANIZATION_ID"), 20)
    if configured:
        try:
            organization = db.get(Organization, int(configured))
        except ValueError as exc:
            raise HTTPException(503, "Public intake workspace is misconfigured") from exc
        if not organization or not organization.is_active:
            raise HTTPException(503, "Public intake workspace is unavailable")
        return organization

    organizations = db.scalars(select(Organization).where(Organization.is_active.is_(True)).limit(2)).all()
    if len(organizations) != 1:
        raise HTTPException(503, "Public intake workspace is not uniquely configured")
    return organizations[0]


def _consent(payload: dict) -> bool:
    return str(payload.get("consent") or "").strip().lower() in {"1", "true", "yes", "on"}


def _bot_sink(payload: dict) -> bool:
    return bool(_text(payload.get("website"), 255))


@router.get("/readiness")
def readiness(db: Session = Depends(get_db)):
    try:
        organization = _workspace(db)
    except HTTPException:
        return {"ready": False, "workspace_resolved": False, "accepts": sorted(KINDS)}
    return {
        "ready": True,
        "workspace_resolved": True,
        "organization": organization.name,
        "accepts": sorted(KINDS),
        "automated_outreach": False,
    }


@router.post("/{kind}")
def submit(kind: str, payload: dict, db: Session = Depends(get_db)):
    if kind not in KINDS:
        raise HTTPException(404, "Unsupported public intake type")
    if _bot_sink(payload):
        return {"accepted": True, "reference": "received"}
    if not _consent(payload):
        raise HTTPException(422, "Consent acknowledgment is required")

    organization = _workspace(db)
    now = datetime.now(timezone.utc)
    source = "sahjony.com"

    if kind == "seller":
        name = _text(payload.get("name"), 160)
        phone = _phone(payload.get("phone"))
        email = _email(payload.get("email"))
        address = _text(payload.get("address"), 255)
        city = _text(payload.get("city"), 100)
        state = _text(payload.get("state"), 2).upper()
        zip_code = _text(payload.get("zip_code"), 12)
        if not all((name, address, city, re.fullmatch(r"[A-Z]{2}", state), zip_code)):
            raise HTTPException(422, "Name and complete property address are required")
        timeline_days = int(_number(payload.get("timeline_days"), 0) or 0) or None
        asking_price = _number(payload.get("asking_price"))
        condition = _text(payload.get("condition"), 1200)
        motivation = _text(payload.get("motivation"), 1200)

        lead = Lead(
            seller_name=name,
            phone=phone,
            email=email,
            source="public_website_seller",
            status="new",
            timeline_days=timeline_days,
            notes=f"Public seller intake. Motivation: {motivation or 'Not provided'}. Condition: {condition or 'Not provided'}.",
        )
        lead.property = Property(
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            property_type=_text(payload.get("property_type"), 50) or "single_family",
            asking_price=asking_price,
            distress_signals=["public_seller_submission"],
        )
        db.add(lead)
        db.flush()
        db.add_all([
            WorkspaceEntity(organization_id=organization.id, entity_type="lead", entity_id=lead.id),
            WorkspaceEntity(organization_id=organization.id, entity_type="property", entity_id=lead.property.id),
            CrmActivity(
                organization_id=organization.id,
                lead_id=lead.id,
                activity_type="public_seller_intake",
                summary=f"New seller website submission for {address}, {city}, {state} {zip_code}",
                metadata_json={
                    "source": source,
                    "communications_consent": True,
                    "consent_scope": "respond_to_submission",
                    "motivation": motivation,
                    "condition": condition,
                    "asking_price": asking_price,
                    "timeline_days": timeline_days,
                    "automated_outreach_authorized": False,
                },
            ),
            FollowUpTask(
                organization_id=organization.id,
                lead_id=lead.id,
                title=f"Acquisitions: qualify website seller lead #{lead.id}",
                status="open",
                priority=90,
                notes="Run the 4 Pillars qualification: Motivation, Timeline, Condition, Price. Do not infer broader marketing consent from this form.",
            ),
        ])
        db.commit()
        return {"accepted": True, "kind": kind, "reference": f"seller-{lead.id}", "next": "acquisitions_review"}

    if kind == "buyer":
        name = _text(payload.get("name"), 160)
        phone = _phone(payload.get("phone"))
        email = _email(payload.get("email"))
        zip_codes = _list(payload.get("zip_codes"))
        if not name or not zip_codes:
            raise HTTPException(422, "Buyer name and at least one target ZIP code are required")
        duplicate = db.scalar(select(Buyer).where(or_(Buyer.phone == phone, Buyer.email == email if email else False)))
        if duplicate:
            return {"accepted": True, "kind": kind, "reference": f"buyer-{duplicate.id}", "duplicate": True}
        buyer = Buyer(
            name=name,
            company=_text(payload.get("company"), 160) or None,
            buyer_type="cash_buyer",
            phone=phone,
            email=email,
            zip_codes=zip_codes,
            asset_types=_list(payload.get("asset_types")) or ["single_family"],
            min_price=_number(payload.get("min_price"), 0) or 0,
            max_price=_number(payload.get("max_price"), 10_000_000) or 10_000_000,
            max_rehab=_number(payload.get("max_rehab"), 500_000) or 500_000,
            closing_days=max(1, int(_number(payload.get("closing_days"), 14) or 14)),
            proof_of_funds_verified=False,
            reliability_score=50,
            response_rate=0,
        )
        db.add(buyer)
        db.flush()
        db.add_all([
            WorkspaceEntity(organization_id=organization.id, entity_type="buyer", entity_id=buyer.id),
            CrmActivity(
                organization_id=organization.id,
                activity_type="public_buyer_intake",
                summary=f"New cash buyer website submission: {name}",
                metadata_json={
                    "buyer_id": buyer.id,
                    "source": source,
                    "communications_consent": True,
                    "proof_of_funds_claimed_ready": bool(payload.get("pof_ready")),
                    "proof_of_funds_verified": False,
                },
            ),
            FollowUpTask(
                organization_id=organization.id,
                title=f"Dispositions: verify buyer #{buyer.id} buying box and POF",
                status="open",
                priority=75,
                notes="POF remains unverified until independently reviewed.",
            ),
        ])
        db.commit()
        return {"accepted": True, "kind": kind, "reference": f"buyer-{buyer.id}", "pof_verified": False}

    name = _text(payload.get("name"), 160)
    email = _email(payload.get("email"))
    phone = _text(payload.get("phone"), 40)
    message = _text(payload.get("message"), 4000)
    if not name or not email or not message:
        raise HTTPException(422, "Name, email, and message are required")
    role = _text(payload.get("role"), 120) if kind == "partner" else "general"
    department = "operations" if kind == "partner" else "support"
    activity = CrmActivity(
        organization_id=organization.id,
        activity_type=f"public_{kind}_intake",
        summary=f"New {kind} website submission from {name}",
        metadata_json={
            "source": source,
            "name": name,
            "email": email,
            "phone": phone,
            "role": role,
            "message": message,
            "communications_consent": True,
            "route_department": department,
        },
    )
    db.add(activity)
    db.flush()
    db.add(FollowUpTask(
        organization_id=organization.id,
        title=f"{department.title()}: respond to {kind} inquiry #{activity.id}",
        status="open",
        priority=60,
        notes=f"From {name} <{email}>. {message[:800]}",
    ))
    db.commit()
    return {"accepted": True, "kind": kind, "reference": f"{kind}-{activity.id}", "route_department": department}

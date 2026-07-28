"""Enforce that every actionable lead is a real, locatable property.

The rule: a lead may not drive outreach, an offer, a campaign, or any other
external action unless its property has been verified against an authoritative
geocoder and carries a coordinate that resolves to a real place on a map.

Verification here means the U.S. Census Bureau matched the address and returned
a coordinate and census geography for it. That is what makes a lead locatable.
It deliberately does not claim the parcel is owned by anyone in particular, is
worth anything in particular, or has a structure standing on it -- those are
separate sources with their own evidence, and inventing them is exactly what
this framework exists to prevent.

Unverified leads are not deleted. They are quarantined: visible, countable, and
blocked from action until they verify or are dismissed. Silently dropping a
record an operator entered would lose work; silently acting on an unverified
one is what this module exists to stop.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .database import get_db
from .intelligence_models import IntelligenceFact
from .models import Lead, Property

router = APIRouter(prefix="/lead-verification", tags=["lead verification gate"])

VERIFIED_SOURCE = "census_geocoder"
# Fields that together prove a lead points at a locatable real-world place.
REQUIRED_VERIFIED_FIELDS = {"latitude", "longitude", "normalized_address"}

# Enforcement is on by default. Turning it off is a deliberate act, and the
# readiness endpoint reports when it has been.
ENFORCE_ENV = "REQUIRE_VERIFIED_LEADS"


def enforcement_enabled() -> bool:
    raw = (os.getenv(ENFORCE_ENV) or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def map_url(latitude: float | None, longitude: float | None, address: str | None = None) -> str | None:
    """Build a Google Maps link.

    Prefers the verified coordinate, which is what makes the pin trustworthy.
    Falls back to the normalized address string only when a coordinate is
    absent, and returns None when neither exists rather than emitting a link
    that would drop a user somewhere arbitrary.
    """
    if latitude is not None and longitude is not None:
        return f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
    if address:
        return f"https://www.google.com/maps/search/?api=1&query={quote(address)}"
    return None


def _scoped_property_ids(db: Session, organization_id: int) -> set[int]:
    return set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
    )).all())


def _verified_fields(db: Session, organization_id: int, property_id: int) -> dict[str, Any]:
    rows = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == organization_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id == property_id,
        IntelligenceFact.source == VERIFIED_SOURCE,
        IntelligenceFact.verification_status == "verified",
    )).all()
    return {row.field_name: (row.value_json or {}).get("value") for row in rows}


def evaluate_property(db: Session, organization_id: int, property_id: int) -> dict[str, Any]:
    """Report whether one property meets the locatable-and-verified bar."""
    row = db.get(Property, property_id)
    if not row:
        return {"property_id": property_id, "verified": False, "reason": "Property not found", "map_url": None}

    fields = _verified_fields(db, organization_id, property_id)
    missing = sorted(REQUIRED_VERIFIED_FIELDS - set(fields))
    has_coordinate = row.latitude is not None and row.longitude is not None
    verified = not missing and has_coordinate

    reasons = []
    if missing:
        reasons.append(f"Missing verified fields: {', '.join(missing)}")
    if not has_coordinate:
        reasons.append("Property has no stored coordinate")

    return {
        "property_id": property_id,
        "address": row.address,
        "city": row.city,
        "state": row.state,
        "zip_code": row.zip_code,
        "verified": verified,
        "locatable": has_coordinate,
        "normalized_address": fields.get("normalized_address"),
        "coordinate": {"latitude": row.latitude, "longitude": row.longitude} if has_coordinate else None,
        "map_url": map_url(row.latitude, row.longitude, fields.get("normalized_address")),
        "reason": "; ".join(reasons) or None,
    }


def assert_lead_is_actionable(db: Session, organization_id: int, lead_id: int) -> dict[str, Any]:
    """Gate an outbound workflow on verification.

    Call this before any step that reaches the outside world. Raises 409 when
    the lead is not backed by a verified, locatable property.
    """
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, f"Lead {lead_id} not found")
    prop = db.scalar(select(Property).where(Property.lead_id == lead_id))
    if not prop:
        raise HTTPException(409, f"Lead {lead_id} has no property and cannot be actioned")

    if prop.id not in _scoped_property_ids(db, organization_id):
        raise HTTPException(404, f"Lead {lead_id} not found")

    evaluation = evaluate_property(db, organization_id, prop.id)
    if not evaluation["verified"] and enforcement_enabled():
        raise HTTPException(
            409,
            f"Lead {lead_id} is not verified against public records and cannot be actioned. "
            f"{evaluation['reason']}. Run /verified-ingest/commit for property {prop.id}.",
        )
    return evaluation


def _lead_rows(db: Session, organization_id: int) -> list[tuple[Lead, Property]]:
    property_ids = _scoped_property_ids(db, organization_id)
    if not property_ids:
        return []
    rows = db.execute(
        select(Lead, Property).join(Property, Property.lead_id == Lead.id).where(Property.id.in_(property_ids))
    ).all()
    return [(lead, prop) for lead, prop in rows]


@router.get("/status")
def status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """How much of the pipeline is backed by real, locatable property data."""
    verified, quarantined = [], []
    for lead, prop in _lead_rows(db, principal.organization_id):
        evaluation = evaluate_property(db, principal.organization_id, prop.id)
        entry = {
            "lead_id": lead.id,
            "seller_name": lead.seller_name,
            **{key: evaluation[key] for key in ("property_id", "address", "city", "state", "verified", "map_url", "reason")},
        }
        (verified if evaluation["verified"] else quarantined).append(entry)

    total = len(verified) + len(quarantined)
    return {
        "organization_id": principal.organization_id,
        "enforcement_enabled": enforcement_enabled(),
        "summary": {
            "total_leads": total,
            "verified_and_locatable": len(verified),
            "quarantined": len(quarantined),
            "coverage_percent": round(100.0 * len(verified) / total, 1) if total else 0.0,
        },
        "verified": verified,
        "quarantined": quarantined,
        "rule": (
            "A lead is actionable only when its property matched an authoritative geocoder and carries a "
            "coordinate that resolves on a map."
        ),
        "remediation": "Run /verified-ingest/commit for the quarantined property ids.",
    }


@router.get("/lead/{lead_id}")
def lead_detail(lead_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, f"Lead {lead_id} not found")
    prop = db.scalar(select(Property).where(Property.lead_id == lead_id))
    if not prop or prop.id not in _scoped_property_ids(db, principal.organization_id):
        raise HTTPException(404, f"Lead {lead_id} not found")

    evaluation = evaluate_property(db, principal.organization_id, prop.id)
    return {
        "organization_id": principal.organization_id,
        "lead_id": lead_id,
        "seller_name": lead.seller_name,
        "enforcement_enabled": enforcement_enabled(),
        "actionable": evaluation["verified"] or not enforcement_enabled(),
        **evaluation,
    }


@router.post("/assert-actionable")
def assert_actionable(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Explicit pre-flight check for an operator about to act on a lead."""
    lead_id = payload.get("lead_id")
    if not isinstance(lead_id, int):
        raise HTTPException(422, "lead_id must be an integer")
    evaluation = assert_lead_is_actionable(db, principal.organization_id, lead_id)
    return {
        "organization_id": principal.organization_id,
        "lead_id": lead_id,
        "actionable": True,
        **evaluation,
    }

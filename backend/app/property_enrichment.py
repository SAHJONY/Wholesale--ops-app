from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .attom_adapter import AttomConfigurationError, AttomLookupError, lookup_attom_property
from .auth import Principal, require_role
from .auth_models import CrmActivity
from .crm import _assert_linked
from .database import get_db
from .models import Lead

router = APIRouter(prefix="/enrichment", tags=["property enrichment"])


def _same(left: Any, right: Any) -> bool:
    if left in (None, "") or right in (None, ""):
        return True
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return abs(float(left) - float(right)) < 0.01
        except (TypeError, ValueError):
            pass
    return str(left).strip().lower() == str(right).strip().lower()


def _preview(lead: Lead, evidence: dict) -> dict:
    prop = lead.property
    remote = evidence.get("property") or {}
    mappings = {
        "address": remote.get("address"),
        "city": remote.get("city"),
        "state": remote.get("state"),
        "zip_code": remote.get("zip_code"),
        "property_type": remote.get("property_type"),
        "bedrooms": remote.get("bedrooms"),
        "bathrooms": remote.get("bathrooms"),
        "sqft": remote.get("sqft"),
        "latitude": remote.get("latitude"),
        "longitude": remote.get("longitude"),
    }
    proposed = {}
    conflicts = []
    unchanged = []
    for field, incoming in mappings.items():
        current = getattr(prop, field)
        if incoming in (None, ""):
            continue
        if current in (None, ""):
            proposed[field] = incoming
        elif _same(current, incoming):
            unchanged.append(field)
        else:
            conflicts.append({"field": field, "current": current, "incoming": incoming})
    owner = evidence.get("owner") or {}
    if owner.get("name") and lead.seller_name and not _same(lead.seller_name, owner.get("name")):
        conflicts.append({
            "field": "legal_owner_vs_seller",
            "current": lead.seller_name,
            "incoming": owner.get("name"),
            "requires": "county_record_verification",
        })
    return {
        "proposed_updates": proposed,
        "conflicts": conflicts,
        "unchanged_fields": unchanged,
        "requires_human_review": bool(conflicts),
    }


async def _lookup_for_lead(lead: Lead) -> dict:
    prop = lead.property
    if not prop:
        raise HTTPException(404, "Lead property not found")
    if str(prop.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    address1 = str(prop.address or "").strip()
    address2 = ", ".join(part for part in (prop.city, prop.state, prop.zip_code) if part)
    if not address1 or not address2:
        raise HTTPException(422, "Complete property address is required")
    try:
        return await lookup_attom_property(address1, address2)
    except AttomConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AttomLookupError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/leads/{lead_id}/attom-preview")
async def preview_attom_enrichment(
    lead_id: int,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    evidence = await _lookup_for_lead(lead)
    return {
        "lead_id": lead.id,
        "provider": "attom",
        "evidence": evidence,
        "review": _preview(lead, evidence),
        "applied": False,
    }


@router.post("/leads/{lead_id}/attom-apply")
async def apply_attom_enrichment(
    lead_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead or not lead.property:
        raise HTTPException(404, "Lead property not found")
    evidence = await _lookup_for_lead(lead)
    review = _preview(lead, evidence)
    payload = payload or {}
    approved_conflict_fields = {str(item) for item in payload.get("approved_conflict_fields", [])}
    force = bool(payload.get("force", False))

    prop = lead.property
    remote = evidence.get("property") or {}
    allowed = ("address", "city", "state", "zip_code", "property_type", "bedrooms", "bathrooms", "sqft", "latitude", "longitude")
    applied = {}
    skipped_conflicts = []
    conflict_fields = {item["field"] for item in review["conflicts"]}
    for field in allowed:
        incoming = remote.get(field)
        if incoming in (None, ""):
            continue
        current = getattr(prop, field)
        is_conflict = field in conflict_fields
        if is_conflict and not (force or field in approved_conflict_fields):
            skipped_conflicts.append(field)
            continue
        if current in (None, "") or force or field in approved_conflict_fields:
            setattr(prop, field, incoming)
            applied[field] = incoming

    activity = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="property_enriched",
        summary=f"ATTOM evidence reviewed for {lead.seller_name}; {len(applied)} fields applied",
        metadata_json={
            "provider": "attom",
            "observed_at": evidence.get("observed_at") or datetime.utcnow().isoformat(),
            "confidence": evidence.get("confidence"),
            "identifiers": evidence.get("identifiers"),
            "owner_evidence": evidence.get("owner"),
            "valuation_evidence": evidence.get("valuation"),
            "last_sale_evidence": evidence.get("last_sale"),
            "source_reference": evidence.get("raw_reference"),
            "verification_required": evidence.get("verification_required"),
            "applied_fields": applied,
            "conflicts": review.get("conflicts"),
            "skipped_conflicts": skipped_conflicts,
        },
    )
    db.add(activity)
    db.commit()
    return {
        "lead_id": lead.id,
        "provider": "attom",
        "applied": applied,
        "skipped_conflicts": skipped_conflicts,
        "conflicts": review["conflicts"],
        "confidence": evidence.get("confidence"),
        "verification_required": evidence.get("verification_required"),
    }

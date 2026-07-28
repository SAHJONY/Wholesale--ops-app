"""Write verified public-record facts onto properties that already exist.

This is the ingest half of the public data provider framework. The framework's
governing rule is that missing evidence is reported as missing and never
inferred or fabricated, so this module writes only the fields an authoritative
source actually establishes.

The U.S. Census Bureau geocoder establishes *geography*: the normalized postal
address, a coordinate, and the FIPS/tract/block identifiers for that location.
It does not establish who owns a parcel, what it is worth, whether a structure
stands on it, or how to contact anyone. Those fields are therefore not
writable here at any confidence, and a caller cannot widen the set.

County ACS statistics are returned for review but deliberately not written as
property facts: an aggregate median is not a fact about an individual parcel,
and storing it as one invites it to be read as a valuation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .database import get_db
from .intelligence_ingest import ingest_provider_facts
from .models import Property
from .nationwide_public_data import resolve_address

router = APIRouter(prefix="/verified-ingest", tags=["verified public record ingest"])

SOURCE_ID = "census_geocoder"
SOURCE_NAME = "U.S. Census Bureau Geocoding Services / MAF-TIGER"
AUTHORITY_TIER = "federal_public_enrichment"

# An exact Census match is authoritative for geography, so these land as
# `verified`. The value is deliberately below 100: the geocoder interpolates
# along address ranges, so the point is authoritative for jurisdiction and
# tract but not for a rooftop.
GEOCODER_CONFIDENCE = 92.0

# The complete set of writable fields. Anything absent from this mapping is not
# written, whatever a caller or a future provider response contains.
WRITABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "normalized_address": ("property", "matched_address"),
    "normalized_street": ("property", "address_components", "street"),
    "normalized_city": ("property", "address_components", "city"),
    "normalized_state": ("property", "address_components", "state"),
    "normalized_zip_code": ("property", "address_components", "zip_code"),
    "latitude": ("property", "coordinates", "latitude"),
    "longitude": ("property", "coordinates", "longitude"),
    "state_fips": ("property", "geography", "state_fips"),
    "county_fips": ("property", "geography", "county_fips"),
    "county_geoid": ("property", "geography", "county_geoid"),
    "county_name": ("property", "geography", "county_name"),
    "census_tract": ("property", "geography", "tract"),
    "census_tract_geoid": ("property", "geography", "tract_geoid"),
    "census_block": ("property", "geography", "block"),
    "census_block_geoid": ("property", "geography", "block_geoid"),
    "census_block_group_geoid": ("property", "geography", "block_group_geoid"),
}

# Stated so the boundary is visible in the API response rather than only in
# this docstring. These are the fields operators most often assume an
# enrichment step filled in.
NEVER_ESTABLISHED_BY_THIS_SOURCE = [
    "owner_name",
    "owner_mailing_address",
    "phone",
    "email",
    "arv",
    "asking_price",
    "mortgage_balance",
    "lien_status",
    "probate_status",
    "tax_delinquency",
    "occupancy_status",
    "structure_exists",
]


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _extract_verified_facts(resolved: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for field_name, path in WRITABLE_FIELDS.items():
        value = _dig(resolved, path)
        if value not in (None, "", [], {}):
            facts[field_name] = value
    return facts


def _load_property(db: Session, organization_id: int, property_id: int) -> Property:
    """Load a property this workspace owns.

    The properties table carries no organization column -- tenancy lives in
    WorkspaceEntity -- so the membership row has to be checked explicitly or
    one workspace could enrich and read another workspace's records.
    """
    owned = db.scalar(select(WorkspaceEntity).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
        WorkspaceEntity.entity_id == property_id,
    ))
    row = db.get(Property, property_id) if owned else None
    if not row:
        raise HTTPException(404, f"Property {property_id} not found")
    return row


async def _resolve_property(db: Session, organization_id: int, property_id: int) -> dict[str, Any]:
    """Geocode one stored property and report what would be written."""
    row = _load_property(db, organization_id, property_id)
    outcome: dict[str, Any] = {
        "property_id": property_id,
        "input": {
            "street": row.address,
            "city": row.city,
            "state": (row.state or "").upper(),
            "zip_code": row.zip_code,
        },
    }
    try:
        resolved = await resolve_address(row.address, row.city, row.state, row.zip_code)
    except HTTPException as exc:
        # A rejection is a reportable outcome, not a pipeline failure: an
        # excluded state or an unmatched address must be visible per address
        # rather than aborting the batch.
        outcome.update({
            "status": "rejected",
            "reason": str(exc.detail),
            "status_code": exc.status_code,
            "facts": {},
        })
        return outcome

    facts = _extract_verified_facts(resolved)
    outcome.update({
        "status": "resolved" if facts else "no_verifiable_fields",
        "matched_address": resolved["property"].get("matched_address"),
        "facts": facts,
        "county_context": resolved.get("county_context"),
        "provenance": resolved.get("provenance"),
        "observed_at": resolved.get("observed_at"),
    })
    return outcome


def _requested_ids(payload: dict[str, Any]) -> list[int]:
    raw = payload.get("property_ids")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(422, "property_ids must be a non-empty list")
    if len(raw) > 100:
        raise HTTPException(422, "property_ids is limited to 100 entries per request")
    try:
        return [int(value) for value in raw]
    except (TypeError, ValueError):
        raise HTTPException(422, "property_ids must contain integers")


def _envelope(principal: Principal, outcomes: list[dict[str, Any]], committed: bool) -> dict[str, Any]:
    return {
        "organization_id": principal.organization_id,
        "source": {"id": SOURCE_ID, "name": SOURCE_NAME, "authority_tier": AUTHORITY_TIER},
        "committed": committed,
        "dry_run": not committed,
        "summary": {
            "requested": len(outcomes),
            "resolved": sum(1 for item in outcomes if item["status"] in {"resolved", "written"}),
            "rejected": sum(1 for item in outcomes if item["status"] == "rejected"),
            "facts_written": sum(item.get("facts_written", 0) for item in outcomes),
        },
        "results": outcomes,
        "writable_fields": sorted(WRITABLE_FIELDS),
        "never_established_by_this_source": NEVER_ESTABLISHED_BY_THIS_SOURCE,
        "limitations": [
            "Census geocodes address ranges and does not prove that a structure exists.",
            "This source does not establish legal ownership, liens, probate, tax delinquency, or seller contact data.",
            "County statistics are aggregate context and are never written as property facts.",
        ],
        "owner_review_required": True,
    }


@router.get("/contract")
def contract(principal: Principal = Depends(get_principal)):
    """Publish what this pipeline may and may not write, without calling out."""
    return {
        "organization_id": principal.organization_id,
        "source": {"id": SOURCE_ID, "name": SOURCE_NAME, "authority_tier": AUTHORITY_TIER},
        "verification_status_written": "verified",
        "confidence": GEOCODER_CONFIDENCE,
        "writable_fields": sorted(WRITABLE_FIELDS),
        "never_established_by_this_source": NEVER_ESTABLISHED_BY_THIS_SOURCE,
        "texas_excluded": True,
        "writes_require_role": "manager",
    }


@router.post("/preview")
async def preview(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    outcomes = [await _resolve_property(db, principal.organization_id, property_id) for property_id in _requested_ids(payload)]
    return _envelope(principal, outcomes, committed=False)


@router.post("/commit")
async def commit(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    outcomes: list[dict[str, Any]] = []
    for property_id in _requested_ids(payload):
        outcome = await _resolve_property(db, principal.organization_id, property_id)
        facts = outcome.get("facts") or {}
        if outcome["status"] != "resolved" or not facts:
            outcome["facts_written"] = 0
            outcomes.append(outcome)
            continue

        observed_at = outcome.get("observed_at")
        result = ingest_provider_facts(
            db,
            principal.organization_id,
            "property",
            property_id,
            SOURCE_ID,
            facts,
            confidence=GEOCODER_CONFIDENCE,
            source_reference=outcome.get("matched_address"),
            verification_status="verified",
            observed_at=datetime.now(timezone.utc),
            metadata={
                "provider": SOURCE_NAME,
                "authority_tier": AUTHORITY_TIER,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "observed_at": observed_at,
                "county_context_reviewed_not_written": bool(outcome.get("county_context")),
            },
        )
        outcome.update({
            "status": "written",
            "facts_written": result["facts_written"],
            "canonical_id": result["canonical_id"],
            "verification_status": result["verification_status"],
            "conflict_count": result["conflict_count"],
        })
        outcomes.append(outcome)

    db.commit()
    return _envelope(principal, outcomes, committed=True)


@router.get("/facts/{property_id}")
def facts_for_property(
    property_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Read back what was actually written, with provenance."""
    from .intelligence_models import IntelligenceFact

    _load_property(db, principal.organization_id, property_id)
    rows = db.scalars(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == principal.organization_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id == property_id,
    ).order_by(IntelligenceFact.field_name)).all()
    return {
        "organization_id": principal.organization_id,
        "property_id": property_id,
        "facts": [{
            "field_name": row.field_name,
            "value": (row.value_json or {}).get("value"),
            "source": row.source,
            "source_reference": row.source_reference,
            "confidence": row.confidence,
            "verification_status": row.verification_status,
            "observed_at": row.observed_at,
        } for row in rows],
    }

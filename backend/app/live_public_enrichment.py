from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Property

router = APIRouter(prefix="/public-data/live-enrichment", tags=["live public data enrichment"])

CENSUS_GEOCODER_URL = os.getenv(
    "CENSUS_GEOCODER_URL",
    "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress",
).strip()


class LiveEnrichmentRequest(BaseModel):
    property_ids: list[int] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    commit: bool = True


def _linked_property_ids(db: Session, organization_id: int) -> set[int]:
    explicit = set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
    )).all())
    lead_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())
    inherited = set(db.scalars(select(Property.id).where(Property.lead_id.in_(lead_ids))).all()) if lead_ids else set()
    return explicit | inherited


def _one_line_address(item: Property) -> str:
    return ", ".join(part for part in [item.address, item.city, item.state, item.zip_code] if part)


def _parse_census_match(payload: dict[str, Any]) -> dict[str, Any] | None:
    matches = (((payload.get("result") or {}).get("addressMatches")) or [])
    if not matches:
        return None
    match = matches[0]
    coordinates = match.get("coordinates") or {}
    geographies = match.get("geographies") or {}
    counties = geographies.get("Counties") or []
    tracts = geographies.get("Census Tracts") or []
    blocks = geographies.get("2020 Census Blocks") or geographies.get("Census Blocks") or []
    return {
        "matched_address": match.get("matchedAddress"),
        "longitude": coordinates.get("x"),
        "latitude": coordinates.get("y"),
        "tiger_line_id": (match.get("tigerLine") or {}).get("tigerLineId"),
        "county": counties[0] if counties else None,
        "tract": tracts[0] if tracts else None,
        "block": blocks[0] if blocks else None,
    }


def _fetch_census(address: str) -> dict[str, Any] | None:
    if not CENSUS_GEOCODER_URL.startswith("https://"):
        raise HTTPException(503, "Census geocoder URL must use HTTPS")
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False) as client:
            response = client.get(CENSUS_GEOCODER_URL, params=params)
            response.raise_for_status()
            return _parse_census_match(response.json())
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Census geocoder unavailable: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise HTTPException(502, "Census geocoder returned invalid JSON") from exc


@router.get("/status")
def live_enrichment_status(principal: Principal = Depends(require_role("manager"))):
    return {
        "organization_id": principal.organization_id,
        "provider": "US Census Geocoder",
        "provider_id": "census_geocoder",
        "endpoint_configured": bool(CENSUS_GEOCODER_URL),
        "public_source": True,
        "credential_required": False,
        "capabilities": ["address_standardization", "coordinates", "county", "tract", "block"],
        "limitations": [
            "Does not verify ownership, liens, seller contact information, distress, ARV, or repair cost.",
            "A no-match result must not be treated as proof that a property does not exist.",
        ],
        "safety": {
            "outbound_messages": False,
            "contracts": False,
            "licensed_data_bypassed": False,
            "texas_excluded": True,
        },
    }


@router.post("/run")
def run_live_enrichment(
    payload: LiveEnrichmentRequest,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    allowed = _linked_property_ids(db, principal.organization_id)
    requested = payload.property_ids or sorted(allowed)
    selected_ids = [property_id for property_id in requested if property_id in allowed][: payload.limit]
    properties = list(db.scalars(select(Property).where(Property.id.in_(selected_ids)).order_by(Property.id.asc())).all()) if selected_ids else []

    results: list[dict[str, Any]] = []
    committed = 0
    skipped = 0
    for item in properties:
        if item.state.upper() == "TX":
            results.append({"property_id": item.id, "status": "excluded", "reason": "Texas excluded"})
            skipped += 1
            continue
        address = _one_line_address(item)
        match = _fetch_census(address)
        if not match:
            results.append({"property_id": item.id, "status": "no_match", "address": address})
            skipped += 1
            continue
        changed = False
        if payload.commit:
            if match.get("latitude") is not None:
                item.latitude = float(match["latitude"])
                changed = True
            if match.get("longitude") is not None:
                item.longitude = float(match["longitude"])
                changed = True
            db.add(CrmActivity(
                organization_id=principal.organization_id,
                user_id=getattr(principal, "user_id", None),
                lead_id=item.lead_id,
                activity_type="public_data_enriched",
                summary="Property geography enriched from the US Census Geocoder",
                metadata_json={
                    "provider_id": "census_geocoder",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "source_url": "https://geocoding.geo.census.gov/",
                    "matched_address": match.get("matched_address"),
                    "county": match.get("county"),
                    "tract": match.get("tract"),
                    "block": match.get("block"),
                    "limitations": ["not ownership verification", "not valuation", "not seller contact data"],
                },
            ))
        if changed:
            committed += 1
        results.append({
            "property_id": item.id,
            "status": "committed" if payload.commit else "preview",
            "address": address,
            "match": match,
        })

    if payload.commit:
        db.commit()

    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_id": "census_geocoder",
        "requested_count": len(requested),
        "processed_count": len(properties),
        "committed_count": committed,
        "skipped_count": skipped,
        "commit": payload.commit,
        "results": results,
        "truth_contract": {
            "real_public_source": True,
            "ownership_verified": False,
            "valuation_verified": False,
            "seller_contact_verified": False,
        },
    }

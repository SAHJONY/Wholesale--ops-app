"""Fetch county distress records and write them as governed facts.

`distress_providers` declares which categories exist and what each may write.
This module is the transport half: it talks to the machine interfaces counties
actually publish, maps rows onto the canonical field names, and writes them
through the same allowlist discipline the Census ingest uses.

Two transports cover the large majority of U.S. county and municipal open-data
portals:

- **Socrata** -- `https://{domain}/resource/{dataset_id}.json`, paginated with
  the SoQL `$limit`/`$offset` parameters.
- **ArcGIS FeatureServer** -- `{service}/FeatureServer/{layer}/query`, paginated
  with `resultOffset`/`resultRecordCount`.

Both are documented, stable, publicly served interfaces. There is no
HTML-parsing transport, so a jurisdiction that publishes only a web page is
reported unavailable rather than harvested.

A jurisdiction is added as configuration, not code, and must pass validation
against the live endpoint before it can be committed. That ordering is
deliberate: a dataset identifier that looks plausible but does not resolve
would otherwise write nothing while appearing configured.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .database import get_db
from .distress_providers import EXCLUDED_STATES, PROVIDERS_BY_ID
from .intelligence_ingest import ingest_provider_facts
from .models import Property

router = APIRouter(prefix="/distress-ingest", tags=["county distress record ingest"])

JURISDICTIONS_FILE_ENV = "DISTRESS_JURISDICTIONS_FILE"
JURISDICTIONS_INLINE_ENV = "DISTRESS_JURISDICTIONS"

REQUEST_TIMEOUT_SECONDS = 20.0
MAX_PAGES = 20
DEFAULT_PAGE_SIZE = 1000
SUPPORTED_TRANSPORTS = {"socrata", "arcgis"}


@dataclass(frozen=True)
class JurisdictionSource:
    """One county dataset feeding one distress category."""

    id: str
    state: str
    county: str
    category: str
    transport: str
    endpoint: str
    # Maps a canonical fact field onto the column that carries it upstream.
    field_map: dict[str, str]
    # Column holding the property address, used to match rows to properties.
    address_field: str
    zip_field: str | None = None
    where: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE

    def spec(self):
        return PROVIDERS_BY_ID[self.category]


def _require(entry: dict[str, Any], key: str, source_id: str) -> str:
    value = str(entry.get(key) or "").strip()
    if not value:
        raise HTTPException(422, f"Jurisdiction '{source_id}' is missing required field '{key}'")
    return value


def _parse_entry(entry: dict[str, Any]) -> JurisdictionSource:
    source_id = str(entry.get("id") or "").strip() or "<unnamed>"
    category = _require(entry, "category", source_id)
    if category not in PROVIDERS_BY_ID:
        raise HTTPException(422, f"Jurisdiction '{source_id}' names unknown category '{category}'")
    spec = PROVIDERS_BY_ID[category]
    if spec.access != "public_record":
        raise HTTPException(422, f"Category '{category}' is licensed and cannot be configured as a county dataset")

    transport = _require(entry, "transport", source_id).lower()
    if transport not in SUPPORTED_TRANSPORTS:
        raise HTTPException(
            422,
            f"Jurisdiction '{source_id}' uses unsupported transport '{transport}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_TRANSPORTS))}. HTML scraping is not supported.",
        )

    state = _require(entry, "state", source_id).upper()
    if state in EXCLUDED_STATES:
        raise HTTPException(409, f"Jurisdiction '{source_id}' is in an excluded state ({state})")

    field_map = entry.get("field_map")
    if not isinstance(field_map, dict) or not field_map:
        raise HTTPException(422, f"Jurisdiction '{source_id}' requires a non-empty field_map")

    # A jurisdiction cannot widen what its category is allowed to establish.
    unknown = sorted(set(field_map) - set(spec.writable_fields))
    if unknown:
        raise HTTPException(
            422,
            f"Jurisdiction '{source_id}' maps fields its category may not write: {', '.join(unknown)}. "
            f"Allowed: {', '.join(spec.writable_fields)}",
        )

    return JurisdictionSource(
        id=_require(entry, "id", source_id),
        state=state,
        county=_require(entry, "county", source_id),
        category=category,
        transport=transport,
        endpoint=_require(entry, "endpoint", source_id),
        field_map={str(k): str(v) for k, v in field_map.items()},
        address_field=_require(entry, "address_field", source_id),
        zip_field=(str(entry["zip_field"]).strip() or None) if entry.get("zip_field") else None,
        where=(str(entry["where"]).strip() or None) if entry.get("where") else None,
        page_size=min(int(entry.get("page_size") or DEFAULT_PAGE_SIZE), DEFAULT_PAGE_SIZE),
    )


def load_jurisdictions() -> list[JurisdictionSource]:
    """Read the configured jurisdiction registry.

    Empty by default. Counties are added here rather than in code, and each
    entry is validated against its live endpoint before it may be committed.
    """
    raw = (os.getenv(JURISDICTIONS_INLINE_ENV) or "").strip()
    if not raw:
        path = (os.getenv(JURISDICTIONS_FILE_ENV) or "").strip()
        if not path:
            return []
        if not os.path.exists(path):
            raise HTTPException(422, f"{JURISDICTIONS_FILE_ENV} points at a missing file: {path}")
        raw = open(path, "r", encoding="utf-8").read()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"Jurisdiction registry is not valid JSON: {exc.msg}")
    entries = parsed.get("jurisdictions") if isinstance(parsed, dict) else parsed
    if not isinstance(entries, list):
        raise HTTPException(422, "Jurisdiction registry must be a list, or an object with a 'jurisdictions' list")
    return [_parse_entry(entry) for entry in entries]


def _get_source(source_id: str) -> JurisdictionSource:
    for source in load_jurisdictions():
        if source.id == source_id:
            return source
    raise HTTPException(404, f"Jurisdiction '{source_id}' is not configured")


# --------------------------------------------------------------- transports --

async def _fetch_socrata(source: JurisdictionSource, limit: int, offset: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"$limit": limit, "$offset": offset}
    if source.where:
        params["$where"] = source.where
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(source.endpoint, params=params, headers={"User-Agent": "sahjony-wholesale-os/1.0"})
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, list) else []


async def _fetch_arcgis(source: JurisdictionSource, limit: int, offset: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "where": source.where or "1=1",
        "outFields": "*",
        "f": "json",
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": limit,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(source.endpoint, params=params, headers={"User-Agent": "sahjony-wholesale-os/1.0"})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        return []
    if payload.get("error"):
        detail = (payload["error"] or {}).get("message") or "ArcGIS service returned an error"
        raise HTTPException(502, f"{source.id}: {detail}")
    return [feature.get("attributes") or {} for feature in payload.get("features") or []]


async def fetch_page(source: JurisdictionSource, limit: int, offset: int) -> list[dict[str, Any]]:
    try:
        if source.transport == "socrata":
            return await _fetch_socrata(source, limit, offset)
        return await _fetch_arcgis(source, limit, offset)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"{source.id}: {type(exc).__name__} contacting {source.transport} endpoint")
    except ValueError:
        raise HTTPException(502, f"{source.id}: endpoint did not return JSON")


async def fetch_rows(source: JurisdictionSource, max_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        remaining = max_rows - len(rows)
        if remaining <= 0:
            break
        batch = await fetch_page(source, min(source.page_size, remaining), page * source.page_size)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < source.page_size:
            break
    return rows


# ------------------------------------------------------------------ mapping --

def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _address_key(address: str, zip_code: str) -> str:
    """Normalize an address for matching. Mirrors the CSV intake key shape."""
    street = re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", _text(address).lower())).strip()
    return f"{street}|{_text(zip_code)[:5]}"


def map_row(source: JurisdictionSource, row: dict[str, Any]) -> dict[str, Any]:
    """Project one upstream row onto canonical fact fields.

    Only fields in the jurisdiction's validated field_map are read, so an
    upstream schema change that adds owner or contact columns cannot introduce
    them here.
    """
    facts: dict[str, Any] = {}
    for canonical_field, upstream_field in source.field_map.items():
        value = row.get(upstream_field)
        if value not in (None, "", [], {}):
            facts[canonical_field] = value
    return facts


def _property_index(db: Session, organization_id: int) -> dict[str, list[int]]:
    """Index this workspace's properties by address key.

    Scoped through WorkspaceEntity: the properties table carries no
    organization column, so an unscoped scan would let one workspace's ingest
    write facts onto another workspace's records.
    """
    scoped_ids = set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
    )).all())
    if not scoped_ids:
        return {}
    index: dict[str, list[int]] = {}
    for row in db.scalars(select(Property).where(Property.id.in_(scoped_ids))).all():
        if (row.state or "").upper() in EXCLUDED_STATES:
            continue
        index.setdefault(_address_key(row.address, row.zip_code), []).append(row.id)
    return index


# ---------------------------------------------------------------- endpoints --

@router.get("/jurisdictions")
def jurisdictions(principal: Principal = Depends(get_principal)):
    sources = load_jurisdictions()
    return {
        "organization_id": principal.organization_id,
        "configured": len(sources),
        "jurisdictions": [{
            "id": source.id,
            "state": source.state,
            "county": source.county,
            "category": source.category,
            "transport": source.transport,
            "mapped_fields": sorted(source.field_map),
            "verification_status": source.spec().verification_status,
            "confidence": source.spec().confidence,
        } for source in sources],
        "registry_env": {"file": JURISDICTIONS_FILE_ENV, "inline": JURISDICTIONS_INLINE_ENV},
        "supported_transports": sorted(SUPPORTED_TRANSPORTS),
        "html_scraping_supported": False,
        "next_step": (
            "Add a jurisdiction to the registry, then run /distress-ingest/validate before committing."
            if not sources
            else "Run /distress-ingest/validate for each jurisdiction, then /distress-ingest/preview."
        ),
    }


@router.post("/validate")
async def validate(payload: dict[str, Any], principal: Principal = Depends(get_principal)):
    """Prove a configured endpoint resolves and carries the mapped columns.

    This must pass before a jurisdiction is trusted: an identifier that looks
    right but does not resolve would otherwise sit in the registry writing
    nothing while appearing healthy.
    """
    source = _get_source(_text(payload.get("jurisdiction_id")))
    rows = await fetch_page(source, limit=1, offset=0)
    if not rows:
        return {
            "organization_id": principal.organization_id,
            "jurisdiction_id": source.id,
            "reachable": True,
            "valid": False,
            "reason": "Endpoint resolved but returned no rows; check the where filter or dataset id.",
        }
    sample = rows[0]
    present = {field: (source.field_map[field] in sample) for field in source.field_map}
    missing = sorted(field for field, ok in present.items() if not ok)
    address_present = source.address_field in sample
    return {
        "organization_id": principal.organization_id,
        "jurisdiction_id": source.id,
        "reachable": True,
        "valid": not missing and address_present,
        "mapped_fields_present": present,
        "missing_mapped_columns": missing,
        "address_field_present": address_present,
        "available_columns": sorted(str(key) for key in sample),
        "reason": None if (not missing and address_present) else "Mapped columns are absent from the upstream schema.",
    }


@router.post("/preview")
async def preview(payload: dict[str, Any], principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    source = _get_source(_text(payload.get("jurisdiction_id")))
    max_rows = min(int(payload.get("max_rows") or 500), MAX_PAGES * DEFAULT_PAGE_SIZE)
    rows = await fetch_rows(source, max_rows)
    index = _property_index(db, principal.organization_id)

    matched, unmatched = [], 0
    for row in rows:
        key = _address_key(_text(row.get(source.address_field)), _text(row.get(source.zip_field)) if source.zip_field else "")
        property_ids = index.get(key)
        if not property_ids:
            unmatched += 1
            continue
        facts = map_row(source, row)
        if not facts:
            continue
        for property_id in property_ids:
            matched.append({"property_id": property_id, "address_key": key, "facts": facts})

    return {
        "organization_id": principal.organization_id,
        "jurisdiction_id": source.id,
        "category": source.category,
        "dry_run": True,
        "committed": False,
        "summary": {"rows_fetched": len(rows), "matched": len(matched), "unmatched_rows": unmatched},
        "matches": matched[:200],
        "verification_status": source.spec().verification_status,
        "owner_review_required": True,
    }


@router.post("/commit")
async def commit(payload: dict[str, Any], principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    source = _get_source(_text(payload.get("jurisdiction_id")))
    spec = source.spec()
    max_rows = min(int(payload.get("max_rows") or 500), MAX_PAGES * DEFAULT_PAGE_SIZE)
    rows = await fetch_rows(source, max_rows)
    index = _property_index(db, principal.organization_id)

    written, unmatched = 0, 0
    touched: list[dict[str, Any]] = []
    for row in rows:
        key = _address_key(_text(row.get(source.address_field)), _text(row.get(source.zip_field)) if source.zip_field else "")
        property_ids = index.get(key)
        if not property_ids:
            unmatched += 1
            continue
        facts = map_row(source, row)
        if not facts:
            continue
        for property_id in property_ids:
            result = ingest_provider_facts(
                db,
                principal.organization_id,
                "property",
                property_id,
                source.category,
                facts,
                confidence=spec.confidence,
                source_reference=f"{source.county}, {source.state} :: {source.id}",
                verification_status=spec.verification_status,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "provider": spec.name,
                    "authority_tier": spec.authority_tier,
                    "jurisdiction": {"state": source.state, "county": source.county},
                    "transport": source.transport,
                },
            )
            written += result["facts_written"]
            touched.append({"property_id": property_id, "facts_written": result["facts_written"]})

    db.commit()
    return {
        "organization_id": principal.organization_id,
        "jurisdiction_id": source.id,
        "category": source.category,
        "committed": True,
        "dry_run": False,
        "summary": {
            "rows_fetched": len(rows),
            "properties_touched": len(touched),
            "facts_written": written,
            "unmatched_rows": unmatched,
        },
        "verification_status": spec.verification_status,
        "owner_review_required": True,
    }

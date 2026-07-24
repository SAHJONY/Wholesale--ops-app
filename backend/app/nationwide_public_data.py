from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal, get_principal

router = APIRouter(prefix="/public-data/nationwide", tags=["nationwide public property enrichment"])

CENSUS_GEOCODER_URL = os.getenv(
    "CENSUS_GEOCODER_URL",
    "https://geocoding.geo.census.gov/geocoder/geographies/address",
)
CENSUS_ACS_URL = os.getenv(
    "CENSUS_ACS_URL",
    "https://api.census.gov/data/2024/acs/acs5",
)
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _first(items: Any) -> dict[str, Any]:
    return items[0] if isinstance(items, list) and items else {}


def _extract_geography(match: dict[str, Any]) -> dict[str, Any]:
    geographies = match.get("geographies") or {}
    states = _first(geographies.get("States"))
    counties = _first(geographies.get("Counties"))
    tracts = _first(geographies.get("Census Tracts"))
    blocks = _first(geographies.get("2020 Census Blocks")) or _first(geographies.get("Census Blocks"))
    block_groups = _first(geographies.get("Census Block Groups"))
    return {
        "state_fips": states.get("STATE") or counties.get("STATE") or tracts.get("STATE"),
        "county_fips": counties.get("COUNTY") or tracts.get("COUNTY"),
        "county_geoid": counties.get("GEOID"),
        "county_name": counties.get("NAME") or counties.get("BASENAME"),
        "tract": tracts.get("TRACT"),
        "tract_geoid": tracts.get("GEOID"),
        "block_group": block_groups.get("BLKGRP"),
        "block_group_geoid": block_groups.get("GEOID"),
        "block": blocks.get("BLOCK"),
        "block_geoid": blocks.get("GEOID"),
    }


def _normalize_match(match: dict[str, Any]) -> dict[str, Any]:
    coordinates = match.get("coordinates") or {}
    address_components = match.get("addressComponents") or {}
    return {
        "matched_address": match.get("matchedAddress"),
        "coordinates": {
            "longitude": coordinates.get("x"),
            "latitude": coordinates.get("y"),
        },
        "address_components": {
            "street": " ".join(
                part
                for part in [
                    _clean(address_components.get("fromAddress")),
                    _clean(address_components.get("preDirection")),
                    _clean(address_components.get("preType")),
                    _clean(address_components.get("streetName")),
                    _clean(address_components.get("suffixType")),
                    _clean(address_components.get("suffixDirection")),
                ]
                if part
            ),
            "city": address_components.get("city"),
            "state": address_components.get("state"),
            "zip_code": address_components.get("zip"),
        },
        "geography": _extract_geography(match),
    }


async def _request_json(url: str, params: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    last_error: Exception | None = None
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.get(url, params=params, headers={"User-Agent": "sahjony-wholesale-os/1.0"})
                response.raise_for_status()
                latency_ms = round((time.perf_counter() - started) * 1000)
                return response.json(), latency_ms, attempt - 1
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(0.25 * (2 ** (attempt - 1)))
    raise HTTPException(502, f"Public provider request failed: {type(last_error).__name__}")


async def _county_context(state_fips: str | None, county_fips: str | None) -> dict[str, Any] | None:
    if not state_fips or not county_fips:
        return None
    params = {
        "get": "NAME,B01003_001E,B25064_001E,B25077_001E,B25001_001E",
        "for": f"county:{county_fips}",
        "in": f"state:{state_fips}",
    }
    try:
        data, latency_ms, retries = await _request_json(CENSUS_ACS_URL, params)
    except HTTPException:
        return None
    if not isinstance(data, list) or len(data) < 2:
        return None
    headers, values = data[0], data[1]
    row = dict(zip(headers, values))

    def number(name: str) -> int | None:
        value = row.get(name)
        try:
            return int(value) if value not in {None, "", "null"} else None
        except (TypeError, ValueError):
            return None

    return {
        "name": row.get("NAME"),
        "population": number("B01003_001E"),
        "median_gross_rent": number("B25064_001E"),
        "median_owner_value": number("B25077_001E"),
        "housing_units": number("B25001_001E"),
        "dataset": "2024 ACS 5-year",
        "latency_ms": latency_ms,
        "retries": retries,
    }


@router.get("/status")
async def status(principal: Principal = Depends(get_principal)):
    services = []
    for provider_id, url in (("census_geocoder", CENSUS_GEOCODER_URL), ("census_acs", CENSUS_ACS_URL)):
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                response = await client.get(url, params={"get": "NAME"} if provider_id == "census_acs" else {"benchmark": "Public_AR_Current", "format": "json"})
            reachable = response.status_code < 500
            status_code = response.status_code
        except httpx.HTTPError:
            reachable = False
            status_code = None
        services.append({
            "id": provider_id,
            "reachable": reachable,
            "status_code": status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        })
    return {
        "organization_id": principal.organization_id,
        "mode": "nationwide_read_only",
        "coverage": "United States, Puerto Rico, and U.S. Island Areas where supported by Census",
        "services": services,
        "ready": all(item["reachable"] for item in services),
        "safety": {
            "database_writes": False,
            "outbound_actions": False,
            "contracts": False,
            "buyer_notifications": False,
            "owner_review_required": True,
            "texas_excluded": True,
        },
    }


@router.post("/enrich-address")
async def enrich_address(payload: dict[str, Any], principal: Principal = Depends(get_principal)):
    street = _clean(payload.get("street") or payload.get("address"))
    city = _clean(payload.get("city"))
    state = _clean(payload.get("state")).upper()
    zip_code = _clean(payload.get("zip_code") or payload.get("zip"))
    if not street or not state:
        raise HTTPException(422, "street/address and state are required")
    if state == "TX":
        raise HTTPException(409, "Texas properties are excluded from SAHJONY wholesale workflows")

    params = {
        "street": street,
        "city": city,
        "state": state,
        "zip": zip_code,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "all",
        "format": "json",
    }
    data, latency_ms, retries = await _request_json(CENSUS_GEOCODER_URL, params)
    matches = (((data.get("result") or {}).get("addressMatches")) or []) if isinstance(data, dict) else []
    if not matches:
        raise HTTPException(404, "Census did not return an address match")
    normalized = _normalize_match(matches[0])
    geography = normalized["geography"]
    county_context = await _county_context(geography.get("state_fips"), geography.get("county_fips"))
    observed_at = datetime.now(timezone.utc).isoformat()
    return {
        "organization_id": principal.organization_id,
        "mode": "nationwide_read_only",
        "input": {"street": street, "city": city, "state": state, "zip_code": zip_code},
        "property": normalized,
        "county_context": county_context,
        "provenance": [
            {
                "provider_id": "census_geocoder",
                "provider": "U.S. Census Bureau Geocoding Services / MAF-TIGER",
                "observed_at": observed_at,
                "authority_tier": "federal_public_enrichment",
                "confidence": "high_for_geography_not_ownership",
                "latency_ms": latency_ms,
                "retries": retries,
            },
            *([{
                "provider_id": "census_acs",
                "provider": "U.S. Census Bureau 2024 ACS 5-year",
                "observed_at": observed_at,
                "authority_tier": "federal_public_statistics",
                "confidence": "high_for_aggregate_county_context",
                "latency_ms": county_context.get("latency_ms"),
                "retries": county_context.get("retries"),
            }] if county_context else []),
        ],
        "limitations": [
            "Census geocodes address ranges and does not prove that a structure exists.",
            "This response does not establish legal ownership, liens, probate, tax delinquency, or seller contact data.",
            "County-level context is aggregate statistical data and not a property valuation.",
        ],
        "workflow": {
            "committed": False,
            "dry_run": True,
            "external_actions_allowed": False,
            "owner_review_required": True,
        },
    }

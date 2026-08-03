"""Discover county distress datasets nationwide.

There is no single nationwide distress dataset. Tax rolls, code enforcement
cases, foreclosure calendars and probate dockets are created by roughly 3,100
counties and many thousands of municipalities, and each publishes on its own
terms. Coverage is therefore built jurisdiction by jurisdiction.

What *is* nationwide is discovery. Two federated catalogs index government
open data across the country:

- **Socrata catalog** -- `api.us.socrata.com/api/catalog/v1`, covering every
  Socrata-powered government portal.
- **ArcGIS Online search** -- `www.arcgis.com/sharing/rest/search`, covering
  published feature services.

Sweeping those turns registry population from manual data entry into a search.
A sweep proposes candidates; it never enables them. Every candidate carries
`status: "unvalidated"` and must pass `/distress-ingest/validate` against the
live endpoint before it can be committed, because a dataset that looks right
from a catalog title may carry different columns or no rows at all.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal, get_principal
from .distress_providers import EXCLUDED_STATES, PROVIDERS_BY_ID

router = APIRouter(prefix="/distress-discovery", tags=["nationwide distress dataset discovery"])

SOCRATA_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
ARCGIS_SEARCH_URL = "https://www.arcgis.com/sharing/rest/search"
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_RESULTS_PER_CATALOG = 100

# Search phrasing per category. These are the terms jurisdictions actually
# title these datasets with; a sweep is a recall exercise, and validation is
# what establishes precision.
CATEGORY_QUERIES: dict[str, tuple[str, ...]] = {
    "tax_delinquency": ("delinquent tax", "tax delinquency", "tax certificate sale", "unpaid property tax"),
    "code_violation": ("code violation", "code enforcement", "unsafe structure", "property maintenance violation"),
    "probate": ("probate case", "probate docket", "estate case"),
    # Judicial track: the artefacts of a filed lawsuit.
    "lis_pendens": ("lis pendens", "pre-foreclosure filing", "foreclosure complaint", "notice of pendency"),
    # Non-judicial track: recorded by the trustee or recorder, no docket exists.
    "notice_of_default": ("notice of default", "default notice", "notice of delinquency"),
    "notice_of_trustee_sale": (
        "notice of trustee sale", "trustee sale", "notice of sale", "substitute trustee",
    ),
    "foreclosure_sale": ("foreclosure sale", "sheriff sale", "tax deed auction", "foreclosure auction"),
    "demolition_permit": ("demolition permit", "demolition", "building permit demolition"),
}


def _public_record_categories() -> list[str]:
    return [
        category for category in CATEGORY_QUERIES
        if PROVIDERS_BY_ID[category].access == "public_record"
    ]


def categories_without_queries() -> list[str]:
    """Public-record categories a sweep cannot find.

    A category with no search terms is invisible to discovery, so adding one to
    the provider registry without adding terms here silently removes it from
    nationwide coverage. That happened when the foreclosure track was split.
    A test asserts this stays empty.
    """
    return sorted(
        spec.id for spec in PROVIDERS_BY_ID.values()
        if spec.access == "public_record" and spec.id not in CATEGORY_QUERIES
    )


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers={"User-Agent": "sahjony-wholesale-os/1.0"})
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def search_socrata(query: str, limit: int) -> list[dict[str, Any]]:
    payload = await _get_json(SOCRATA_CATALOG_URL, {"q": query, "only": "dataset", "limit": limit})
    candidates = []
    for item in payload.get("results") or []:
        resource = item.get("resource") or {}
        domain = (item.get("metadata") or {}).get("domain")
        dataset_id = resource.get("id")
        if not domain or not dataset_id:
            continue
        candidates.append({
            "catalog": "socrata",
            "transport": "socrata",
            "domain": domain,
            "dataset_id": dataset_id,
            "title": resource.get("name"),
            "description": (resource.get("description") or "")[:400],
            "endpoint": f"https://{domain}/resource/{dataset_id}.json",
            "permalink": item.get("permalink"),
        })
    return candidates


async def search_arcgis(query: str, limit: int) -> list[dict[str, Any]]:
    payload = await _get_json(ARCGIS_SEARCH_URL, {
        "q": f'{query} AND (type:"Feature Service")',
        "f": "json",
        "num": limit,
    })
    candidates = []
    for item in payload.get("results") or []:
        service_url = item.get("url")
        if not service_url or "FeatureServer" not in service_url:
            continue
        candidates.append({
            "catalog": "arcgis",
            "transport": "arcgis",
            "domain": item.get("owner"),
            "dataset_id": item.get("id"),
            "title": item.get("title"),
            "description": (item.get("snippet") or "")[:400],
            # Layer 0 is the common default; validation confirms the real layer.
            "endpoint": f"{service_url.rstrip('/')}/0/query",
            "permalink": f"https://www.arcgis.com/home/item.html?id={item.get('id')}",
        })
    return candidates


STATE_NAMES: dict[str, str] = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "DC": "district of columbia",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois",
    "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana",
    "ME": "maine", "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota",
    "MS": "mississippi", "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico", "NY": "new york",
    "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west virginia", "WI": "wisconsin",
    "WY": "wyoming",
}


def _matches_state(candidate: dict[str, Any], states: set[str]) -> bool:
    """Whether a catalog hit plausibly belongs to one of the requested states.

    Substring matching on the abbreviation is unusable here, and was: "IN"
    matched every dataset titled "Building" or "Index", "CA" matched "vacant"
    and "Chicago", "OR" matched "Records", "LA" matched "Violation". A sweep
    filtered that way returns most of the country whichever state you ask for,
    which is worse than no filter because it looks like it worked.

    Three signals are accepted instead: the full state name anywhere, the
    abbreviation as a whole word, and the abbreviation as a domain label, which
    is how government portals encode it (``data.ca.gov``, ``gis.tn.us``).
    """
    if not states:
        return True

    domain = str(candidate.get("domain") or "").lower()
    haystack = " ".join(
        str(candidate.get(key) or "") for key in ("domain", "title", "description")
    ).lower()

    for state in states:
        code = state.lower()
        name = STATE_NAMES.get(state.upper())
        if name and name in haystack:
            return True
        # Whole word only: "in" must not match "building".
        if re.search(rf"\b{re.escape(code)}\b", haystack):
            return True
        # A domain label, e.g. data.ca.gov or maps.tn.us.
        if re.search(rf"(^|\.){re.escape(code)}\.", domain):
            return True
    return False


@router.get("/categories")
def categories(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "categories": [{
            "id": category,
            "queries": list(queries),
            "procedure": PROVIDERS_BY_ID[category].procedure,
            "verification_status": PROVIDERS_BY_ID[category].verification_status,
            "writable_fields": list(PROVIDERS_BY_ID[category].writable_fields),
        } for category, queries in CATEGORY_QUERIES.items()],
        "catalogs": [
            {"id": "socrata", "url": SOCRATA_CATALOG_URL, "scope": "nationwide federated government portals"},
            {"id": "arcgis", "url": ARCGIS_SEARCH_URL, "scope": "nationwide published feature services"},
        ],
        "note": (
            "No single nationwide distress dataset exists; coverage is assembled per jurisdiction. "
            "A sweep proposes candidates and never enables them."
        ),
    }


@router.post("/sweep")
async def sweep(payload: dict[str, Any], principal: Principal = Depends(get_principal)):
    """Search the federated catalogs for candidate datasets.

    Returns registry-shaped entries marked unvalidated. Nothing is enabled and
    nothing is written.
    """
    requested = payload.get("categories") or _public_record_categories()
    if not isinstance(requested, list):
        raise HTTPException(422, "categories must be a list")
    unknown = sorted(set(requested) - set(CATEGORY_QUERIES))
    if unknown:
        raise HTTPException(422, f"Unknown categories: {', '.join(unknown)}")

    states = {str(item).strip().upper() for item in (payload.get("states") or []) if str(item).strip()}
    excluded = sorted(states & EXCLUDED_STATES)
    states -= EXCLUDED_STATES
    limit = min(int(payload.get("limit_per_query") or 20), MAX_RESULTS_PER_CATALOG)
    catalogs = payload.get("catalogs") or ["socrata", "arcgis"]

    results: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, str]] = []
    for category in requested:
        found: dict[str, dict[str, Any]] = {}
        for query in CATEGORY_QUERIES[category]:
            for catalog, search in (("socrata", search_socrata), ("arcgis", search_arcgis)):
                if catalog not in catalogs:
                    continue
                try:
                    hits = await search(query, limit)
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append({"catalog": catalog, "query": query, "error": type(exc).__name__})
                    continue
                for hit in hits:
                    if not _matches_state(hit, states):
                        continue
                    found[hit["endpoint"]] = {
                        **hit,
                        "category": category,
                        "status": "unvalidated",
                        # Which county office creates this record, so an
                        # operator can tell whether a hit is even plausible for
                        # the state before spending a validation call on it.
                        "procedure": PROVIDERS_BY_ID[category].procedure,
                        "suggested_registry_entry": {
                            "id": f"{hit['catalog']}-{hit['dataset_id']}-{category}",
                            "state": "REPLACE",
                            "county": hit.get("title") or "REPLACE",
                            "category": category,
                            "transport": hit["transport"],
                            "endpoint": hit["endpoint"],
                            "address_field": "REPLACE",
                            "field_map": {field: "REPLACE" for field in PROVIDERS_BY_ID[category].writable_fields},
                        },
                    }
        results[category] = list(found.values())

    total = sum(len(items) for items in results.values())
    return {
        "organization_id": principal.organization_id,
        "swept_categories": requested,
        "states_filter": sorted(states),
        "excluded_states_ignored": excluded,
        "summary": {
            "total_candidates": total,
            "by_category": {category: len(items) for category, items in results.items()},
            "catalog_errors": len(errors),
        },
        "candidates": results,
        "errors": errors,
        "next_steps": [
            "Fill in state, county, address_field and field_map for each candidate you keep.",
            "Add it to the jurisdiction registry (DISTRESS_JURISDICTIONS_FILE).",
            "Run POST /distress-ingest/validate before committing; a catalog hit is not proof of schema.",
        ],
        "committed": False,
        "enabled_anything": False,
    }

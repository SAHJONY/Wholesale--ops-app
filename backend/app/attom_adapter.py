import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .provider_errors import PropertyDataConfigurationError, PropertyDataLookupError

ATTOM_BASE_URL = os.getenv("ATTOM_BASE_URL", "https://api.gateway.attomdata.com/propertyapi/v1.0.0")


# Subclassing the shared errors lets callers match on the provider-neutral type
# while every existing `except AttomConfigurationError` keeps working.
class AttomConfigurationError(PropertyDataConfigurationError):
    pass


class AttomLookupError(PropertyDataLookupError):
    pass


def _dig(value: Any, *path: str, default=None):
    current = value
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def _number(value: Any, integer: bool = False):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
        return int(round(parsed)) if integer else parsed
    except (TypeError, ValueError):
        return None


def _owner_name(owner: dict) -> str | None:
    names = []
    for key in ("owner1", "owner2", "owner3", "owner4"):
        item = owner.get(key) or {}
        first = str(item.get("firstNameAndMi") or item.get("firstnameandmi") or "").strip()
        last = str(item.get("lastName") or item.get("lastname") or "").strip()
        full = " ".join(part for part in (first, last) if part).strip()
        if full:
            names.append(full)
    additional = str(owner.get("ownerAfterSpouse") or "").strip()
    if additional:
        names.append(additional)
    return "; ".join(names) or None


def normalize_attom_property(payload: dict) -> dict:
    properties = payload.get("property") or payload.get("properties") or []
    if isinstance(properties, dict):
        properties = [properties]
    if not properties:
        raise AttomLookupError("ATTOM returned no property match")

    item = properties[0]
    address = item.get("address") or {}
    summary = item.get("summary") or {}
    building = item.get("building") or {}
    building_summary = building.get("summary") or {}
    size = building.get("size") or {}
    rooms = building.get("rooms") or {}
    assessment = item.get("assessment") or {}
    owner = assessment.get("owner") or {}
    identifier = item.get("identifier") or {}
    location = item.get("location") or {}
    sale = item.get("sale") or {}
    sale_amount = sale.get("amount") or {}
    vintage = item.get("vintage") or {}

    normalized = {
        "provider": "attom",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_published_at": vintage.get("pubDate"),
        "source_last_modified_at": vintage.get("lastModified"),
        "confidence": 0.9 if address.get("matchCode") in {"ExaStr", "Exact", "1"} else 0.78,
        "verification_required": [
            "county_assessor_for_current_owner",
            "county_recorder_for_deed_and_mortgage",
            "human_review_before_offer",
        ],
        "identifiers": {
            "attom_id": identifier.get("attomId") or identifier.get("Id"),
            "apn": identifier.get("apn"),
            "fips": identifier.get("fips"),
        },
        "property": {
            "address": address.get("line1") or address.get("oneLine"),
            "city": address.get("locality"),
            "state": address.get("countrySubd"),
            "zip_code": address.get("postal1"),
            "property_type": summary.get("propType") or summary.get("propertyType") or summary.get("propSubType"),
            "bedrooms": _number(rooms.get("beds") or building_summary.get("beds"), integer=True),
            "bathrooms": _number(rooms.get("bathsTotal") or rooms.get("bathsFull") or building_summary.get("bathsTotal")),
            "sqft": _number(size.get("livingSize") or size.get("universalSize") or building_summary.get("size"), integer=True),
            "year_built": _number(summary.get("yearBuilt"), integer=True),
            "latitude": _number(location.get("latitude")),
            "longitude": _number(location.get("longitude")),
        },
        "owner": {
            "name": _owner_name(owner),
            "mailing_address": owner.get("mailingAddressOneline"),
            "absentee_status": owner.get("absenteeOwnerStatus") or summary.get("absenteeInd"),
            "owner_type": owner.get("type") or owner.get("description"),
            "corporate_indicator": owner.get("corporateIndicator"),
        },
        "valuation": {
            "assessed_total": _number(_dig(assessment, "assessed", "assdTtlValue") or assessment.get("fullCashValue")),
            "market_total": _number(_dig(assessment, "market", "mktTtlValue")),
            "tax_year": _dig(assessment, "tax", "taxYear"),
            "tax_amount": _number(_dig(assessment, "tax", "taxAmt")),
        },
        "last_sale": {
            "date": sale.get("saleTransDate") or sale.get("saleSearchDate"),
            "amount": _number(sale_amount.get("saleAmt")),
            "seller_name": sale.get("sellerName"),
            "arms_length": sale.get("armsLengthIdent"),
        },
        "raw_reference": {
            "endpoint": "/property/expandedprofile",
            "attom_id": identifier.get("attomId") or identifier.get("Id"),
        },
    }
    return normalized


async def lookup_attom_property(address1: str, address2: str) -> dict:
    api_key = os.getenv("ATTOM_API_KEY")
    if not api_key:
        raise AttomConfigurationError("ATTOM_API_KEY is not configured")
    params = {"address1": address1, "address2": address2}
    headers = {"accept": "application/json", "apikey": api_key}
    url = f"{ATTOM_BASE_URL.rstrip('/')}/property/expandedprofile"
    timeout = httpx.Timeout(20.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise AttomLookupError(f"ATTOM connection failed: {exc.__class__.__name__}") from exc
    if response.status_code == 401:
        raise AttomConfigurationError("ATTOM rejected the API key")
    if response.status_code == 429:
        raise AttomLookupError("ATTOM rate limit reached")
    if response.status_code >= 400:
        raise AttomLookupError(f"ATTOM lookup failed with status {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AttomLookupError("ATTOM returned invalid JSON") from exc
    return normalize_attom_property(payload)

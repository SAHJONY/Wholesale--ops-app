import base64
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .provider_errors import PropertyDataConfigurationError, PropertyDataLookupError

# Smarty US Enrichment API. "search" resolves a street address rather than a
# SmartyKey; "property/principal" is the dataset and subset carrying the owner,
# valuation, tax, and sale attributes this workflow needs.
SMARTY_BASE_URL = os.getenv("SMARTY_ENRICHMENT_BASE_URL", "https://us-enrichment.api.smarty.com/lookup")
SMARTY_DATASET_PATH = "search/property/principal"

# Smarty's principal subset carries no match-quality field, so confidence cannot
# be derived the way ATTOM's matchCode allows. It is fixed below ATTOM's exact
# match value so a Smarty answer never outranks a verified one, and county
# verification stays mandatory either way.
SMARTY_CONFIDENCE = 0.8


class SmartyConfigurationError(PropertyDataConfigurationError):
    pass


class SmartyLookupError(PropertyDataLookupError):
    pass


def _number(value: Any, integer: bool = False):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
        return int(round(parsed)) if integer else parsed
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _owner_name(attributes: dict) -> str | None:
    names: list[str] = []
    for key in (
        "owner_full_name",
        "deed_owner_full_name",
        "deed_owner_full_name2",
        "deed_owner_full_name3",
        "deed_owner_full_name4",
    ):
        name = _text(attributes.get(key))
        if name and name not in names:
            names.append(name)
    if not names:
        combined = " ".join(
            part for part in (_text(attributes.get("first_name")), _text(attributes.get("last_name"))) if part
        )
        if combined:
            names.append(combined)
    return "; ".join(names) or None


def _owner_type(attributes: dict) -> str | None:
    # Smarty reports entity shape as separate flags rather than one type field.
    # Both matter before an offer: a company or trust owner changes who signs.
    trust = _text(attributes.get("trust_description"))
    if trust:
        return trust
    flag = _text(attributes.get("company_flag"))
    return "company" if flag and flag.upper() in {"Y", "YES", "TRUE", "1"} else None


def _split_locality(address2: str) -> dict:
    """Split the "CITY, ST, ZIP" string the callers build into query parameters.

    Returning an empty dict is the signal to fall back to a freeform lookup
    rather than to guess at which token means what.
    """
    parts = [part.strip() for part in str(address2 or "").split(",") if part.strip()]
    if len(parts) >= 3:
        return {"city": parts[0], "state": parts[1], "zipcode": parts[2]}
    if len(parts) == 2 and not parts[1].replace("-", "").isdigit():
        return {"city": parts[0], "state": parts[1]}
    return {}


def normalize_smarty_property(payload: Any) -> dict:
    """Reshape a Smarty principal response into the provider-neutral evidence dict.

    The shape matches normalize_attom_property exactly, because downstream fact
    ingestion, conflict detection, and the county-verification gate all read
    these keys and must not care which provider answered.
    """
    candidates = payload if isinstance(payload, list) else [payload]
    candidates = [item for item in candidates if isinstance(item, dict)]
    if not candidates:
        raise SmartyLookupError("Smarty returned no property match")

    item = candidates[0]
    attributes = item.get("attributes") or {}
    if not attributes:
        raise SmartyLookupError("Smarty returned a match without property attributes")

    # Smarty exposes both an assessor sale and a recorded deed sale. The deed is
    # the contract-critical one, so it wins when both are present.
    sale_date = _text(attributes.get("deed_sale_date")) or _text(attributes.get("sale_date"))
    sale_amount = _number(attributes.get("deed_sale_price"))
    if sale_amount is None:
        sale_amount = _number(attributes.get("sale_amount"))

    return {
        "provider": "smarty",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_published_at": _text(attributes.get("assessor_taxroll_update")),
        "source_last_modified_at": None,
        "confidence": SMARTY_CONFIDENCE,
        "verification_required": [
            "county_assessor_for_current_owner",
            "county_recorder_for_deed_and_mortgage",
            "human_review_before_offer",
        ],
        "identifiers": {
            "smarty_key": _text(item.get("smarty_key")),
            "apn": _text(attributes.get("parcel_account_number")),
            "fips": _text(attributes.get("contact_mailing_fips")),
        },
        "property": {
            "address": _text(attributes.get("property_address_full")) or _text(attributes.get("matched_address")),
            "city": _text(attributes.get("property_address_city")) or _text(attributes.get("city_name")),
            "state": _text(attributes.get("property_address_state")) or _text(attributes.get("state_abbreviation")),
            "zip_code": _text(attributes.get("property_address_zipcode")) or _text(attributes.get("zipcode")),
            "property_type": _text(attributes.get("land_use_standard")) or _text(attributes.get("land_use_code")),
            "bedrooms": _number(attributes.get("bedrooms"), integer=True),
            "bathrooms": _number(attributes.get("bathrooms_total")),
            "sqft": _number(attributes.get("building_sqft"), integer=True),
            "year_built": _number(attributes.get("year_built") or attributes.get("effective_year_built"), integer=True),
            "latitude": _number(attributes.get("latitude")),
            "longitude": _number(attributes.get("longitude")),
        },
        "owner": {
            "name": _owner_name(attributes),
            "mailing_address": _text(attributes.get("contact_full_address")),
            "absentee_status": _text(attributes.get("owner_occupancy_status")),
            "owner_type": _owner_type(attributes),
            "corporate_indicator": _text(attributes.get("company_flag")),
        },
        "valuation": {
            "assessed_total": _number(attributes.get("assessed_value")),
            "market_total": _number(attributes.get("total_market_value")),
            "tax_year": _text(attributes.get("tax_assess_year")) or _text(attributes.get("tax_fiscal_year")),
            "tax_amount": _number(attributes.get("tax_billed_amount")),
        },
        "last_sale": {
            "date": sale_date,
            "amount": sale_amount,
            "seller_name": None,  # Not present in the principal subset.
            "arms_length": None,  # Smarty exposes no arms-length flag here.
        },
        "raw_reference": {
            "endpoint": f"/{SMARTY_DATASET_PATH}",
            "smarty_key": _text(item.get("smarty_key")),
        },
    }


def _credentials() -> tuple[str, str]:
    auth_id = (os.getenv("SMARTY_AUTH_ID") or "").strip()
    auth_token = (os.getenv("SMARTY_AUTH_TOKEN") or "").strip()
    if not auth_id or not auth_token:
        missing = " and ".join(
            name for name, value in (("SMARTY_AUTH_ID", auth_id), ("SMARTY_AUTH_TOKEN", auth_token)) if not value
        )
        raise SmartyConfigurationError(f"{missing} is not configured")
    return auth_id, auth_token


async def lookup_smarty_property(address1: str, address2: str) -> dict:
    auth_id, auth_token = _credentials()

    params: dict[str, str] = {}
    locality = _split_locality(address2)
    if locality:
        params["street"] = address1
        params.update(locality)
    else:
        # Without a parseable city/state, let Smarty parse the whole thing rather
        # than send a street with no locality, which matches the wrong county.
        params["freeform"] = ", ".join(part for part in (address1, address2) if part)

    license_key = (os.getenv("SMARTY_LICENSE") or "").strip()
    if license_key:
        params["license"] = license_key

    # Basic auth over the header form keeps the token out of the URL, and so out
    # of access logs and exception traces. Smarty accepts either.
    encoded = base64.b64encode(f"{auth_id}:{auth_token}".encode()).decode()
    headers = {"accept": "application/json", "authorization": f"Basic {encoded}"}
    url = f"{SMARTY_BASE_URL.rstrip('/')}/{SMARTY_DATASET_PATH}"

    timeout = httpx.Timeout(20.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SmartyLookupError(f"Smarty connection failed: {exc.__class__.__name__}") from exc

    if response.status_code in {401, 402, 403}:
        raise SmartyConfigurationError("Smarty rejected the secret key pair or the plan does not include property data")
    if response.status_code == 429:
        raise SmartyLookupError("Smarty rate limit reached")
    if response.status_code == 404:
        raise SmartyLookupError("Smarty returned no property match")
    if response.status_code >= 400:
        raise SmartyLookupError(f"Smarty lookup failed with status {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SmartyLookupError("Smarty returned invalid JSON") from exc
    return normalize_smarty_property(payload)

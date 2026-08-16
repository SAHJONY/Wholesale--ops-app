from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .acquisition_intake import ALLOWED_SOURCES, import_records
from .auth import Principal

MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_RECORDS = 1000
REQUEST_TIMEOUT_SECONDS = 30.0
ATTOM_BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/snapshot"
ATTOM_MARKETS_PER_RUN = 5
ATTOM_PAGE_SIZE = 20

# One stable seed ZIP per state. Runs rotate through this list so the system can
# discover nationwide property candidates without hammering one market or
# requiring a manually maintained external feed URL. These are discovery seeds,
# not assertions that the ZIPs are wholesale markets or that returned properties
# are distressed.
NATIONWIDE_SEED_ZIPS: tuple[tuple[str, str], ...] = (
    ("AL", "35203"), ("AK", "99501"), ("AZ", "85004"), ("AR", "72201"),
    ("CA", "90012"), ("CO", "80202"), ("CT", "06103"), ("DE", "19801"),
    ("FL", "32801"), ("GA", "30303"), ("HI", "96813"), ("ID", "83702"),
    ("IL", "60602"), ("IN", "46204"), ("IA", "50309"), ("KS", "67202"),
    ("KY", "40202"), ("LA", "70112"), ("ME", "04101"), ("MD", "21201"),
    ("MA", "02108"), ("MI", "48226"), ("MN", "55401"), ("MS", "39201"),
    ("MO", "64106"), ("MT", "59101"), ("NE", "68102"), ("NV", "89101"),
    ("NH", "03101"), ("NJ", "07102"), ("NM", "87102"), ("NY", "10001"),
    ("NC", "28202"), ("ND", "58102"), ("OH", "43215"), ("OK", "73102"),
    ("OR", "97204"), ("PA", "19102"), ("RI", "02903"), ("SC", "29201"),
    ("SD", "57104"), ("TN", "37219"), ("TX", "75201"), ("UT", "84111"),
    ("VT", "05401"), ("VA", "23219"), ("WA", "98101"), ("WV", "25301"),
    ("WI", "53202"), ("WY", "82001"),
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_true(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in _TRUE_VALUES


def acquisition_feed_status() -> dict[str, Any]:
    url = str(os.getenv("AUTONOMOUS_PROPERTY_FEED_URL") or "").strip()
    parsed = urlparse(url)
    external_configured = bool(url)
    attom_configured = bool(str(os.getenv("ATTOM_API_KEY") or "").strip())
    provider_mode = "external_https" if external_configured else ("attom_internal" if attom_configured else "unconfigured")
    configured = external_configured or attom_configured
    secure = parsed.scheme == "https" if external_configured else attom_configured
    auto_enabled = attom_configured and not external_configured
    enabled = _env_true("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION") or auto_enabled
    source = (
        str(os.getenv("AUTONOMOUS_PROPERTY_FEED_SOURCE") or "other").strip().lower()
        if external_configured
        else ("attom" if attom_configured else "other")
    )
    return {
        "enabled": enabled,
        "configured": configured,
        "secure": secure,
        "host": parsed.hostname if external_configured else ("api.gateway.attomdata.com" if attom_configured else None),
        "source": source,
        "provider_mode": provider_mode,
        "auto_configured": auto_enabled,
        "review_only": True,
        "outreach_allowed": False,
        "max_records_per_run": MAX_RECORDS,
        "markets_per_run": ATTOM_MARKETS_PER_RUN if provider_mode == "attom_internal" else None,
        "market_rotation": "50_state_seed_rotation" if provider_mode == "attom_internal" else None,
    }


def _feed_config() -> dict[str, Any]:
    status = acquisition_feed_status()
    if not status["enabled"]:
        raise RuntimeError("Autonomous property acquisition is disabled")
    if not status["configured"]:
        raise RuntimeError("No authorized acquisition provider is configured")
    if not status["secure"]:
        raise RuntimeError("Autonomous property feed must use HTTPS")
    source = status["source"]
    if source not in ALLOWED_SOURCES:
        raise RuntimeError("AUTONOMOUS_PROPERTY_FEED_SOURCE is unsupported")

    if status["provider_mode"] == "attom_internal":
        api_key = str(os.getenv("ATTOM_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("ATTOM_API_KEY is not configured")
        return {
            "mode": "attom_internal",
            "source": "attom",
            "url": ATTOM_BASE_URL,
            "headers": {
                "Accept": "application/json",
                "APIKey": api_key,
                "User-Agent": "sahjony-wholesale-os/1.0",
            },
        }

    headers = {"Accept": "application/json", "User-Agent": "sahjony-wholesale-os/1.0"}
    token = str(os.getenv("AUTONOMOUS_PROPERTY_FEED_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return {
        "mode": "external_https",
        "source": source,
        "url": str(os.environ["AUTONOMOUS_PROPERTY_FEED_URL"]).strip(),
        "headers": headers,
    }


def _extract_records(data: Any) -> list[dict[str, Any]]:
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise RuntimeError("Property feed response must be an array or an object containing records")
    if len(records) > MAX_RECORDS:
        raise RuntimeError(f"Property feed exceeds {MAX_RECORDS} records per run")
    return records


def _attom_properties(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    records = data.get("property")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict)]
    return []


def _attom_record(item: dict[str, Any], seed_state: str, seed_zip: str) -> dict[str, Any] | None:
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    identifier = item.get("identifier") if isinstance(item.get("identifier"), dict) else {}
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    building = item.get("building") if isinstance(item.get("building"), dict) else {}
    rooms = building.get("rooms") if isinstance(building.get("rooms"), dict) else {}
    size = building.get("size") if isinstance(building.get("size"), dict) else {}
    location = item.get("location") if isinstance(item.get("location"), dict) else {}

    street = str(address.get("line1") or "").strip()
    city = str(address.get("locality") or "").strip()
    state = str(address.get("countrySubd") or seed_state or "").strip().upper()
    zip_code = str(address.get("postal1") or seed_zip or "").strip()
    if not all((street, city, state, zip_code)):
        return None

    propclass = str(summary.get("propclass") or summary.get("proptype") or "").lower()
    if propclass and not any(token in propclass for token in ("single", "sfr", "residential")):
        return None

    return {
        "address": street,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "source": "attom",
        "property_type": "single_family",
        "bedrooms": rooms.get("beds"),
        "bathrooms": rooms.get("bathstotal") or rooms.get("bathstotalcalc"),
        "sqft": size.get("universalsize") or size.get("livingsize"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "external_id": str(identifier.get("attomId") or identifier.get("Id") or "").strip(),
        "distress_signals": [],
        "provider_evidence": {
            "provider": "attom",
            "seed_state": seed_state,
            "seed_zip": seed_zip,
            "owner_verified": False,
            "distress_verified": False,
        },
    }


def _rotating_markets(now: datetime | None = None) -> list[tuple[str, str]]:
    current = now or datetime.now(timezone.utc)
    start = (current.toordinal() * ATTOM_MARKETS_PER_RUN) % len(NATIONWIDE_SEED_ZIPS)
    return [NATIONWIDE_SEED_ZIPS[(start + offset) % len(NATIONWIDE_SEED_ZIPS)] for offset in range(ATTOM_MARKETS_PER_RUN)]


async def _run_attom_discovery(client: httpx.AsyncClient, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for state, zip_code in _rotating_markets():
        try:
            response = await client.get(
                config["url"],
                headers=config["headers"],
                params={"postalCode": zip_code, "propertyType": "sfr", "pageSize": ATTOM_PAGE_SIZE},
            )
            response.raise_for_status()
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_FEED_BYTES or len(response.content) > MAX_FEED_BYTES:
                warnings.append(f"{state}:{zip_code}:response_too_large")
                continue
            try:
                payload = response.json()
            except ValueError:
                warnings.append(f"{state}:{zip_code}:invalid_json")
                continue
            market_records = [
                normalized
                for item in _attom_properties(payload)
                if (normalized := _attom_record(item, state, zip_code)) is not None
            ]
            records.extend(market_records)
        except httpx.HTTPError as exc:
            warnings.append(f"{state}:{zip_code}:{type(exc).__name__}")

    if not records and warnings:
        raise RuntimeError("ATTOM discovery returned no usable properties; provider requests failed")
    return records[:MAX_RECORDS], warnings


async def run_autonomous_property_acquisition(
    db: Session,
    principal: Principal,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    config = _feed_config()
    source = str(config["source"])
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)
    warnings: list[str] = []
    try:
        if config["mode"] == "attom_internal":
            records, warnings = await _run_attom_discovery(active_client, config)
        else:
            response = await active_client.get(config["url"], headers=config["headers"])
            response.raise_for_status()
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > MAX_FEED_BYTES or len(response.content) > MAX_FEED_BYTES:
                raise RuntimeError("Property feed response exceeds 5 MB")
            try:
                records = _extract_records(response.json())
            except ValueError as exc:
                raise RuntimeError("Property feed did not return valid JSON") from exc
    finally:
        if owns_client:
            await active_client.aclose()

    if not records:
        return {
            "status": "completed", "source": source, "received": 0,
            "created": 0, "updated": 0, "duplicate": 0, "rejected": 0,
            "review_only": True, "provider_warnings": warnings,
        }

    result = import_records(
        {
            "source": source,
            "records": records,
            "external_batch_id": f"autonomous-{datetime.now(timezone.utc).isoformat()}",
            "_autonomous_review_only": True,
        },
        principal,
        db,
    )
    return {
        "status": "completed",
        **result,
        "provider_mode": config["mode"],
        "provider_warnings": warnings,
        "review_only": True,
    }

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


def acquisition_feed_status() -> dict[str, Any]:
    url = str(os.getenv("AUTONOMOUS_PROPERTY_FEED_URL") or "").strip()
    parsed = urlparse(url)
    configured = bool(url)
    secure = parsed.scheme == "https"
    return {
        "enabled": str(os.getenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION") or "").lower() in {"1", "true", "yes", "on"},
        "configured": configured,
        "secure": secure,
        "host": parsed.hostname if configured else None,
        "source": str(os.getenv("AUTONOMOUS_PROPERTY_FEED_SOURCE") or "other").strip().lower(),
        "review_only": True,
        "outreach_allowed": False,
        "max_records_per_run": MAX_RECORDS,
    }


def _feed_config() -> tuple[str, str, dict[str, str]]:
    status = acquisition_feed_status()
    if not status["enabled"]:
        raise RuntimeError("Autonomous property acquisition is disabled")
    if not status["configured"]:
        raise RuntimeError("AUTONOMOUS_PROPERTY_FEED_URL is not configured")
    if not status["secure"]:
        raise RuntimeError("Autonomous property feed must use HTTPS")
    source = status["source"]
    if source not in ALLOWED_SOURCES:
        raise RuntimeError("AUTONOMOUS_PROPERTY_FEED_SOURCE is unsupported")
    headers = {"Accept": "application/json", "User-Agent": "sahjony-wholesale-os/1.0"}
    token = str(os.getenv("AUTONOMOUS_PROPERTY_FEED_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return str(os.environ["AUTONOMOUS_PROPERTY_FEED_URL"]).strip(), source, headers


def _extract_records(data: Any) -> list[dict[str, Any]]:
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise RuntimeError("Property feed response must be an array or an object containing records")
    if len(records) > MAX_RECORDS:
        raise RuntimeError(f"Property feed exceeds {MAX_RECORDS} records per run")
    return records


async def run_autonomous_property_acquisition(
    db: Session,
    principal: Principal,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    url, source, headers = _feed_config()
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)
    try:
        response = await active_client.get(url, headers=headers)
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
            "review_only": True,
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
    return {"status": "completed", **result}

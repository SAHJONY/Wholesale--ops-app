from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_models import CrmActivity
from .database import get_db

router = APIRouter(prefix="/internal/bland-diagnostics", tags=["Bland diagnostics one-time runner"])
AUTH_ACTIVITY = "bland_diagnostic_authorization"
AUTH_TTL = timedelta(minutes=30)


def _clean_key() -> tuple[str, list[str]]:
    raw = str(os.getenv("BLAND_AI_API_KEY") or "")
    value = raw.strip()
    warnings: list[str] = []
    if raw != value:
        warnings.append("leading_or_trailing_whitespace")
    if len(value) >= 2 and value[0] in {'\"', "'", "“", "‘"} and value[-1] in {'\"', "'", "”", "’"}:
        warnings.append("wrapped_in_quotes")
        value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        warnings.append("bearer_prefix_present")
        value = value[7:].strip()
    return value, warnings


def _nonce_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_provider_message(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    message = payload.get("message") or payload.get("error")
    if not message and isinstance(payload.get("errors"), list) and payload["errors"]:
        first = payload["errors"][0]
        message = first.get("error") if isinstance(first, dict) else str(first)
    return str(message)[:300] if message else None


@router.get("/run-once")
async def run_once(nonce: str = Query(min_length=20, max_length=200), db: Session = Depends(get_db)):
    threshold = datetime.now(timezone.utc) - AUTH_TTL
    rows = db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == 1,
        CrmActivity.activity_type == AUTH_ACTIVITY,
        CrmActivity.created_at >= threshold,
    ).order_by(CrmActivity.id.desc()).limit(20)).all()
    expected = _nonce_hash(nonce)
    authorization = None
    for row in rows:
        meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if meta.get("status") == "pending" and secrets.compare_digest(str(meta.get("nonce_hash") or ""), expected):
            authorization = row
            break
    if not authorization:
        raise HTTPException(404, "One-time Bland diagnostic authorization not found, expired, or consumed")

    api_key, key_warnings = _clean_key()
    if not api_key:
        result = {
            "status": "blocked",
            "root_cause": "missing_api_key",
            "api_key_present": False,
            "api_key_format_warnings": key_warnings,
            "call_placed": False,
            "secret_values_exposed": False,
        }
    else:
        async with httpx.AsyncClient(timeout=20) as client:
            me_response = await client.get(
                "https://api.bland.ai/v1/me",
                headers={"authorization": api_key, "Accept": "application/json"},
            )
            try:
                me_payload = me_response.json()
            except ValueError:
                me_payload = None

            memberships_response = None
            memberships_payload = None
            if 200 <= me_response.status_code < 300:
                memberships_response = await client.get(
                    "https://api.bland.ai/v1/orgs/self/memberships",
                    headers={"authorization": api_key, "Accept": "application/json"},
                )
                try:
                    memberships_payload = memberships_response.json()
                except ValueError:
                    memberships_payload = None

        configured_org = str(os.getenv("BLAND_INBOUND_ORGANIZATION_ID") or "").strip()
        memberships = []
        if isinstance(memberships_payload, dict) and isinstance(memberships_payload.get("data"), list):
            memberships = [item for item in memberships_payload["data"] if isinstance(item, dict)]
        org_ids = {str(item.get("org_id") or "") for item in memberships}
        org_names = [str(item.get("org_display_name") or "") for item in memberships if item.get("org_display_name")]

        if me_response.status_code in {401, 403}:
            root_cause = "provider_rejected_api_key"
        elif not (200 <= me_response.status_code < 300):
            root_cause = "bland_account_probe_failed"
        elif configured_org and memberships and configured_org not in org_ids:
            root_cause = "api_key_org_mismatch"
        else:
            root_cause = None

        result = {
            "status": "healthy" if root_cause is None else "failed",
            "root_cause": root_cause,
            "api_key_present": True,
            "api_key_length": len(api_key),
            "api_key_format_warnings": key_warnings,
            "me": {
                "http_status": me_response.status_code,
                "provider_message": _safe_provider_message(me_payload),
                "account_status": me_payload.get("status") if isinstance(me_payload, dict) else None,
            },
            "memberships": {
                "probe_http_status": memberships_response.status_code if memberships_response is not None else None,
                "organization_names": org_names,
                "configured_org_present": bool(configured_org),
                "configured_org_match": configured_org in org_ids if configured_org and memberships else None,
            },
            "call_placed": False,
            "secret_values_exposed": False,
        }

    meta = dict(authorization.metadata_json or {})
    meta["status"] = "consumed"
    meta["consumed_at"] = datetime.now(timezone.utc).isoformat()
    meta["diagnostic_root_cause"] = result.get("root_cause")
    authorization.metadata_json = meta
    authorization.summary = "Owner-authorized one-time Bland diagnostic consumed"
    db.commit()
    return result

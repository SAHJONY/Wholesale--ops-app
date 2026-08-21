import os
from datetime import datetime, timezone
from typing import Any

import httpx


DEFAULT_BATCHDATA_SKIPTRACE_URL = "https://api.batchdata.com/api/v1/property/skip-trace"


class BatchDataConfigurationError(RuntimeError):
    pass


class BatchDataLookupError(RuntimeError):
    pass


def _first(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "y"}:
        return True
    if text in {"false", "no", "0", "n"}:
        return False
    return None


def _normalize_phone(item: Any) -> dict | None:
    if isinstance(item, str):
        number = item.strip()
        if not number:
            return None
        return {"number": number, "type": None, "carrier": None, "dnc": None, "litigator": None, "confidence": None}
    if not isinstance(item, dict):
        return None
    number = str(item.get("number") or item.get("phone") or item.get("phoneNumber") or item.get("value") or "").strip()
    if not number:
        return None
    confidence = item.get("confidence") or item.get("score") or item.get("rank")
    return {
        "number": number,
        "type": item.get("type") or item.get("phoneType") or item.get("lineType"),
        "carrier": item.get("carrier") or item.get("carrierName"),
        "dnc": _as_bool(item.get("dnc") if "dnc" in item else item.get("isDnc")),
        "litigator": _as_bool(item.get("litigator") if "litigator" in item else item.get("isLitigator")),
        "confidence": confidence,
    }


def _normalize_email(item: Any) -> dict | None:
    if isinstance(item, str):
        email = item.strip().lower()
        return {"email": email, "confidence": None, "valid": None} if email else None
    if not isinstance(item, dict):
        return None
    email = str(item.get("email") or item.get("address") or item.get("value") or "").strip().lower()
    if not email:
        return None
    return {
        "email": email,
        "confidence": item.get("confidence") or item.get("score") or item.get("rank"),
        "valid": _as_bool(item.get("valid") if "valid" in item else item.get("isValid")),
    }


def normalize_batchdata_contacts(payload: dict) -> dict:
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    result = root.get("result") if isinstance(root, dict) and isinstance(root.get("result"), dict) else root
    if isinstance(result, dict) and isinstance(result.get("results"), list) and result["results"]:
        result = result["results"][0]
    if isinstance(result, dict) and isinstance(result.get("persons"), list) and result["persons"]:
        person = result["persons"][0]
    else:
        person = result if isinstance(result, dict) else {}

    phone_candidates = (
        person.get("phones")
        or person.get("phoneNumbers")
        or person.get("phone_numbers")
        or root.get("phones") if isinstance(root, dict) else []
    ) or []
    email_candidates = (
        person.get("emails")
        or person.get("emailAddresses")
        or person.get("email_addresses")
        or root.get("emails") if isinstance(root, dict) else []
    ) or []

    phones = []
    seen_phones = set()
    for item in phone_candidates if isinstance(phone_candidates, list) else [phone_candidates]:
        normalized = _normalize_phone(item)
        if normalized and normalized["number"] not in seen_phones:
            seen_phones.add(normalized["number"])
            phones.append(normalized)

    emails = []
    seen_emails = set()
    for item in email_candidates if isinstance(email_candidates, list) else [email_candidates]:
        normalized = _normalize_email(item)
        if normalized and normalized["email"] not in seen_emails:
            seen_emails.add(normalized["email"])
            emails.append(normalized)

    owner_name = (
        person.get("name")
        or person.get("fullName")
        or " ".join(str(person.get(key) or "").strip() for key in ("firstName", "middleName", "lastName")).strip()
        or None
    )
    request_id = payload.get("requestId") or payload.get("request_id") or _first(payload, "meta", "requestId")
    safe_phones = [item for item in phones if item.get("dnc") is not True and item.get("litigator") is not True]
    blocked_phones = [item for item in phones if item.get("dnc") is True or item.get("litigator") is True]

    return {
        "provider": "batchdata",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "owner_name": owner_name,
        "phones": phones,
        "emails": emails,
        "safe_phone_candidates": safe_phones,
        "blocked_phone_candidates": blocked_phones,
        "outreach_allowed": bool(safe_phones) and not bool(blocked_phones),
        "confidence": person.get("confidence") or person.get("matchScore") or result.get("confidence") if isinstance(result, dict) else None,
        "raw_reference": {"request_id": request_id},
        "verification_required": [
            "confirm_right_party_contact",
            "recheck_national_and_state_dnc_before_each_outreach",
            "enforce_opt_out_and_quiet_hours",
        ],
    }


async def lookup_batchdata_contacts(*, address: str, city: str, state: str, zip_code: str, owner_name: str | None = None) -> dict:
    api_key = os.getenv("BATCHDATA_API_KEY", "").strip()
    endpoint = os.getenv("BATCHDATA_SKIPTRACE_URL", "").strip() or DEFAULT_BATCHDATA_SKIPTRACE_URL
    if not api_key:
        raise BatchDataConfigurationError("BATCHDATA_API_KEY is not configured")

    auth_header = os.getenv("BATCHDATA_AUTH_HEADER", "Authorization").strip() or "Authorization"
    auth_scheme = os.getenv("BATCHDATA_AUTH_SCHEME", "Bearer").strip()
    auth_value = f"{auth_scheme} {api_key}".strip() if auth_scheme else api_key
    payload = {
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "ownerName": owner_name,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            response = await client.post(endpoint, json=payload, headers={auth_header: auth_value, "Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise BatchDataLookupError(f"BatchData connection failed: {exc}") from exc

    if response.status_code in {401, 403}:
        raise BatchDataLookupError("BatchData authentication failed; verify key, endpoint, auth header, and auth scheme")
    if response.status_code == 429:
        raise BatchDataLookupError("BatchData rate limit reached")
    if response.status_code >= 400:
        detail = response.text[:300]
        raise BatchDataLookupError(f"BatchData returned HTTP {response.status_code}: {detail}")
    try:
        data = response.json()
    except ValueError as exc:
        raise BatchDataLookupError("BatchData returned invalid JSON") from exc
    normalized = normalize_batchdata_contacts(data)
    if not normalized["phones"] and not normalized["emails"]:
        raise BatchDataLookupError("BatchData returned no contact matches")
    return normalized

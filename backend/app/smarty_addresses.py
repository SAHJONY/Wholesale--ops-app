"""Smarty US address verification, and the vacancy signal it carries.

Two things this gives the desk that the free Census geocoder does not.

**Proof the address is real.** The standing rule is that every lead must be a
real property locatable on a map. Smarty validates against USPS delivery data
and returns a DPV match code, so "this address exists and receives mail" stops
being an assumption and becomes a recorded fact with a source.

**A vacancy signal.** USPS marks an address vacant when mail has gone
undeliverable for roughly 90 days. That is one of the strongest distress
indicators in this business and it was missing from the provider set entirely.
It stacks alongside tax delinquency and code violations.

The wording matters and is deliberately narrow throughout: USPS reports the
address as **vacant for delivery purposes**. That is not the same claim as "the
building is empty" -- a forwarded owner, a seasonal property, or a new build
can all read vacant. It is strong evidence, not a finding, and nothing here
phrases it as more.

**Quota is a first-class concern.** The Core subscription is 1,000 lookups.
Re-verifying an address the system has already verified spends a lookup to
learn something it was told last week, so verified results are cached and the
cache is checked before the network. A bulk path that quietly burned the
allowance on duplicates would be the easiest possible way to waste it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .config import settings
from .database import get_db
from .intelligence_models import IntelligenceFact

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enrichment/address", tags=["address verification"])

US_STREET_URL = "https://us-street.api.smarty.com/street-address"

# Source id used on every fact this module writes, so a vacancy signal can be
# traced back to USPS-derived data rather than to an unnamed enrichment step.
SOURCE_ID = "usps_vacancy"
VACANCY_FIELD = "usps_reported_vacant"

# DPV confirmation codes. "Y" and "S" are deliverable; "D" is deliverable to the
# building but missing a unit, which for a single-family target is still a real
# address. Anything else is not confirmed and must not be treated as verified.
DPV_CONFIRMED = frozenset({"Y", "S", "D"})


def is_configured() -> bool:
    return bool(settings.smarty_auth_id and settings.smarty_auth_token)


def _credentials() -> dict[str, str]:
    if not is_configured():
        raise HTTPException(503, "SMARTY_AUTH_ID and SMARTY_AUTH_TOKEN are not configured")
    return {"auth-id": settings.smarty_auth_id, "auth-token": settings.smarty_auth_token}


def interpret(candidate: dict[str, Any]) -> dict[str, Any]:
    """Turn one Smarty candidate into the facts the system stores.

    Split out from the network call so the interpretation of DPV codes -- the
    part that decides whether an address counts as verified -- can be tested
    without spending a lookup.
    """
    analysis = candidate.get("analysis") or {}
    metadata = candidate.get("metadata") or {}
    components = candidate.get("components") or {}

    dpv_match = str(analysis.get("dpv_match_code") or "").upper()
    vacant = str(analysis.get("dpv_vacant") or "").upper() == "Y"
    no_stat = str(analysis.get("dpv_no_stat") or "").upper() == "Y"

    return {
        "delivery_line": candidate.get("delivery_line_1"),
        "last_line": candidate.get("last_line"),
        "verified": dpv_match in DPV_CONFIRMED,
        "dpv_match_code": dpv_match or None,
        "latitude": metadata.get("latitude"),
        "longitude": metadata.get("longitude"),
        "county": metadata.get("county_name"),
        "county_fips": metadata.get("county_fips"),
        "zip": components.get("zipcode"),
        "plus4": components.get("plus4_code"),
        # Residential Delivery Indicator: filters commercial addresses out of a
        # single-family campaign before anyone pays to skip trace them.
        "residential": metadata.get("rdi") == "Residential",
        "usps_reported_vacant": vacant,
        # "No-stat" means USPS is not delivering there at all -- under
        # construction, demolished, or a vacant lot. Distinct from vacant, and
        # worth surfacing separately rather than folding into it.
        "usps_no_stat": no_stat,
        "vacancy_note": (
            "USPS reports this address as vacant for delivery purposes -- mail has been "
            "undeliverable for roughly 90 days. Strong evidence, not a finding: a forwarded "
            "owner, a seasonal property or a new build can all read vacant."
            if vacant else
            "USPS does not report this address as vacant."
        ),
    }


def _cached_fact(db: Session, organization_id: int, address_key: str) -> IntelligenceFact | None:
    return db.scalar(
        select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_type == "address",
            IntelligenceFact.field_name == "smarty_verification",
            IntelligenceFact.source_reference == address_key,
        )
    )


def _address_key(street: str, city: str, state: str, zipcode: str) -> str:
    return " ".join(part.strip().lower() for part in (street, city, state, zipcode) if part)


def verify(
    db: Session,
    organization_id: int,
    street: str,
    city: str = "",
    state: str = "",
    zipcode: str = "",
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """Verify one address, spending a lookup only when there isn't a cached one."""
    key = _address_key(street, city, state, zipcode)
    if not key:
        raise HTTPException(422, "An address is required")

    if not refresh:
        cached = _cached_fact(db, organization_id, key)
        if cached:
            return {**cached.value_json, "cached": True, "observed_at": (
                cached.observed_at.isoformat() if cached.observed_at else None
            )}

    params = {**_credentials(), "candidates": "1", "match": "strict"}
    params["street"] = street
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if zipcode:
        params["zipcode"] = zipcode

    try:
        response = httpx.get(US_STREET_URL, params=params, timeout=20)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Smarty unreachable: {type(exc).__name__}") from exc

    if response.status_code == 401:
        raise HTTPException(502, "Smarty rejected the credentials (check SMARTY_AUTH_ID/TOKEN)")
    if response.status_code == 402:
        raise HTTPException(502, "Smarty subscription is out of lookups")
    if response.status_code >= 400:
        raise HTTPException(502, f"Smarty returned {response.status_code}")

    candidates = response.json()
    if not candidates:
        # No candidate is a real answer: USPS does not recognise this address.
        # It is recorded as such rather than retried, because a retry spends a
        # second lookup to be told the same thing.
        result = {
            "verified": False,
            "dpv_match_code": None,
            "usps_reported_vacant": False,
            "note": "USPS returned no candidate for this address. It could not be verified.",
        }
    else:
        result = interpret(candidates[0])

    now = datetime.now(timezone.utc)
    _store(db, organization_id, key, result, now)
    return {**result, "cached": False, "observed_at": now.isoformat()}


def _store(db: Session, organization_id: int, key: str, result: dict, now: datetime) -> None:
    """Cache the verification, and record vacancy as a stackable distress fact."""
    existing = _cached_fact(db, organization_id, key)
    if existing:
        existing.value_json = result
        existing.observed_at = now
    else:
        db.add(IntelligenceFact(
            organization_id=organization_id,
            entity_type="address",
            entity_id=0,
            field_name="smarty_verification",
            value_json=result,
            source="smarty_us_street",
            source_reference=key,
            confidence=95.0 if result.get("verified") else 0.0,
            verification_status="verified" if result.get("verified") else "unverified",
            observed_at=now,
        ))
    db.commit()


def record_vacancy_signal(
    db: Session, organization_id: int, property_id: int, result: dict, now: datetime | None = None
) -> bool:
    """Write the vacancy signal against a property so it stacks.

    Returns whether a signal was asserted. Only writes when USPS actually
    reports vacancy -- storing ``False`` would be a truthful fact but the
    stacking scorer already treats a stored ``False`` as absence, so writing it
    costs a row and changes nothing.
    """
    if not result.get("usps_reported_vacant"):
        return False

    now = now or datetime.now(timezone.utc)
    existing = db.scalar(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == organization_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id == property_id,
        IntelligenceFact.field_name == VACANCY_FIELD,
        IntelligenceFact.source == SOURCE_ID,
    ))
    if existing:
        existing.value_json = True
        existing.observed_at = now
    else:
        db.add(IntelligenceFact(
            organization_id=organization_id,
            entity_type="property",
            entity_id=property_id,
            field_name=VACANCY_FIELD,
            value_json=True,
            source=SOURCE_ID,
            confidence=80.0,
            verification_status="verified",
            observed_at=now,
        ))
    db.commit()
    return True


@router.post("/verify")
def verify_address(
    payload: dict[str, Any],
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Verify one address. Records a vacancy signal when property_id is given."""
    result = verify(
        db, principal.organization_id,
        street=str(payload.get("street") or ""),
        city=str(payload.get("city") or ""),
        state=str(payload.get("state") or ""),
        zipcode=str(payload.get("zipcode") or ""),
        refresh=bool(payload.get("refresh")),
    )

    property_id = payload.get("property_id")
    if property_id:
        result["vacancy_signal_recorded"] = record_vacancy_signal(
            db, principal.organization_id, int(property_id), result
        )
    return result


@router.get("/status")
def status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Configuration and how much of the allowance this workspace has spent.

    The count is of addresses this system has verified, which is the number a
    caller can act on. Smarty's own meter is the billing authority.
    """
    cached = db.scalar(select(IntelligenceFact).where(
        IntelligenceFact.organization_id == principal.organization_id,
        IntelligenceFact.entity_type == "address",
        IntelligenceFact.field_name == "smarty_verification",
    ).with_only_columns(IntelligenceFact.id)) is not None

    verified_count = len(db.scalars(select(IntelligenceFact.id).where(
        IntelligenceFact.organization_id == principal.organization_id,
        IntelligenceFact.entity_type == "address",
        IntelligenceFact.field_name == "smarty_verification",
    )).all())

    return {
        "organization_id": principal.organization_id,
        "configured": is_configured(),
        "addresses_verified": verified_count,
        "has_cache": cached,
        "note": (
            "Cached verifications are served without spending a lookup. Pass refresh=true "
            "only when an address may have changed status -- vacancy is the field that moves."
        ),
        "advisory": (
            "USPS vacancy means mail has been undeliverable for roughly 90 days. It is strong "
            "evidence of an empty property, not proof of one, and never a statement about who "
            "owns it or whether they want to sell."
        ),
    }

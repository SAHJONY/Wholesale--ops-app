"""Governed distress-signal and listing providers.

Distress signals are genuine public records: tax delinquency rolls, code
violation and unsafe-structure cases, probate dockets, lis pendens, foreclosure
and sheriff-sale calendars, demolition permits. Counties and municipalities
publish these through documented open-data APIs, overwhelmingly Socrata or
ArcGIS FeatureServer. This module talks to those APIs.

It does not scrape. There is no HTML-parsing transport here and adding one
would contradict the framework's stated boundary, which is that connectors use
published interfaces and never bypass access controls. A jurisdiction that
publishes only a web page is reported as unavailable rather than harvested.

For-sale-by-owner inventory is deliberately modelled differently. FSBO is not a
public record: no government body maintains an authoritative FSBO dataset, and
the sites that aggregate it license their data under terms that forbid
automated collection. FSBO is therefore a licensed provider slot in the same
tier as MLS/IDX -- disabled by default, and unlocked only by an operator who
supplies an authorized endpoint and records the agreement that permits it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends

from .auth import Principal, get_principal

router = APIRouter(prefix="/distress-data", tags=["public distress and listing providers"])

EXCLUDED_STATES = {"TX"}


@dataclass(frozen=True)
class ProviderSpec:
    """One distress or listing category and the fields it may establish."""

    id: str
    name: str
    category: str
    # `public_record` sources are published by the authority that creates the
    # record. `licensed` sources require a commercial agreement.
    access: str
    authority_tier: str
    # Verification tier a fact from this category may claim. Only records held
    # by the originating authority are allowed to reach "verified".
    verification_status: str
    confidence: float
    writable_fields: tuple[str, ...]
    feature_flag: str
    endpoint_env: str
    license_required: bool = False
    # Transports are documented machine interfaces only.
    supported_transports: tuple[str, ...] = ("socrata", "arcgis")
    # Which foreclosure track creates this record, and therefore which county
    # office holds it. "any" marks categories that are not foreclosure-specific
    # (tax rolls, code cases, permits) and "both" marks records that occur on
    # either track. See foreclosure_procedure.py.
    procedure: str = "any"
    notes: str = ""


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="tax_delinquency",
        name="County tax delinquency roll",
        category="distress",
        access="public_record",
        authority_tier="county_tax_authority",
        verification_status="verified",
        confidence=90.0,
        writable_fields=("tax_delinquent", "tax_delinquent_years", "tax_amount_due", "tax_roll_observed_at"),
        feature_flag="DISTRESS_TAX_DELINQUENCY_ENABLED",
        endpoint_env="DISTRESS_TAX_DELINQUENCY_ENDPOINT",
    ),
    ProviderSpec(
        id="code_violation",
        name="Municipal code violation and unsafe structure cases",
        category="distress",
        access="public_record",
        authority_tier="municipal_code_enforcement",
        verification_status="verified",
        confidence=85.0,
        writable_fields=("code_violation_open", "code_violation_count", "code_violation_last_case", "unsafe_structure"),
        feature_flag="DISTRESS_CODE_VIOLATION_ENABLED",
        endpoint_env="DISTRESS_CODE_VIOLATION_ENDPOINT",
    ),
    ProviderSpec(
        id="probate",
        name="Probate court docket",
        category="distress",
        access="public_record",
        authority_tier="county_court",
        verification_status="partially_verified",
        confidence=70.0,
        writable_fields=("probate_case_open", "probate_case_number", "probate_filed_at"),
        feature_flag="DISTRESS_PROBATE_ENABLED",
        endpoint_env="DISTRESS_PROBATE_ENDPOINT",
        notes=(
            "A probate docket names a decedent's estate, not a parcel. Matching a case to a property is an "
            "inference, so facts from this source stay below verified until a recorder document confirms them."
        ),
    ),
    ProviderSpec(
        id="lis_pendens",
        name="Lis pendens and pre-foreclosure filings",
        category="distress",
        access="public_record",
        authority_tier="county_recorder",
        verification_status="verified",
        confidence=88.0,
        writable_fields=("lis_pendens_filed", "lis_pendens_filed_at", "lis_pendens_instrument"),
        feature_flag="DISTRESS_LIS_PENDENS_ENABLED",
        endpoint_env="DISTRESS_LIS_PENDENS_ENDPOINT",
        procedure="judicial",
        notes=(
            "A lis pendens is recorded against the parcel but arises from a filed lawsuit, so it "
            "appears on the judicial track. Non-judicial states produce no equivalent."
        ),
    ),
    ProviderSpec(
        id="notice_of_default",
        name="Notice of default",
        category="distress",
        access="public_record",
        authority_tier="county_recorder",
        verification_status="verified",
        confidence=88.0,
        writable_fields=("notice_of_default_recorded", "notice_of_default_date", "notice_of_default_instrument"),
        feature_flag="DISTRESS_NOD_ENABLED",
        endpoint_env="DISTRESS_NOD_ENDPOINT",
        procedure="non_judicial",
        notes=(
            "Opens the non-judicial track and starts the statutory cure period. There is no court "
            "docket to search; the record sits with the recorder."
        ),
    ),
    ProviderSpec(
        id="notice_of_trustee_sale",
        name="Notice of trustee sale",
        category="distress",
        access="public_record",
        authority_tier="county_recorder_or_substitute_trustee",
        verification_status="verified",
        confidence=88.0,
        writable_fields=("trustee_sale_scheduled", "trustee_sale_date", "trustee_sale_instrument"),
        feature_flag="DISTRESS_NTS_ENABLED",
        endpoint_env="DISTRESS_NTS_ENDPOINT",
        procedure="non_judicial",
        notes=(
            "Published inside a statutory window before sale, sometimes by the substitute trustee "
            "rather than the county. The window is short, so a stale feed is worse than none."
        ),
    ),
    ProviderSpec(
        id="foreclosure_sale",
        name="Foreclosure and sheriff sale calendar",
        category="distress",
        access="public_record",
        authority_tier="county_sheriff_or_trustee",
        verification_status="verified",
        confidence=88.0,
        writable_fields=("foreclosure_sale_scheduled", "foreclosure_sale_date", "foreclosure_case_number"),
        feature_flag="DISTRESS_FORECLOSURE_ENABLED",
        endpoint_env="DISTRESS_FORECLOSURE_ENDPOINT",
        procedure="both",
        notes=(
            "The sale itself occurs on either track -- sheriff's sale after judgment, trustee's sale "
            "under a power of sale -- so this category is configured against whichever office runs it."
        ),
    ),
    ProviderSpec(
        id="cash_purchase_deed",
        name="Recorded deed transfers",
        category="buyer_signal",
        access="public_record",
        authority_tier="county_recorder",
        verification_status="verified",
        confidence=90.0,
        # A deed establishes who took title, when, and for how much. It writes
        # nothing onto the property's distress profile: buying a house is not a
        # sign of distress, it is a sign of a buyer.
        writable_fields=("last_sale_price", "last_sale_date", "last_sale_instrument", "last_grantee"),
        feature_flag="BUYER_DEED_ENABLED",
        endpoint_env="BUYER_DEED_ENDPOINT",
        notes=(
            "Feeds cash-buyer discovery. A deed alone never proves a cash purchase; that requires "
            "searching the mortgage index for the same parcel and finding nothing, which is a "
            "separate dataset (BUYER_MORTGAGE_INDEX_ENDPOINT). Without it, purchases are reported "
            "as unconfirmed rather than assumed to be cash."
        ),
    ),
    ProviderSpec(
        id="demolition_permit",
        name="Building and demolition permits",
        category="distress",
        access="public_record",
        authority_tier="municipal_permitting",
        verification_status="verified",
        confidence=80.0,
        writable_fields=("demolition_permit_open", "permit_last_issued_at", "permit_type"),
        feature_flag="DISTRESS_PERMIT_ENABLED",
        endpoint_env="DISTRESS_PERMIT_ENDPOINT",
    ),
    ProviderSpec(
        id="fsbo_listing",
        name="For-sale-by-owner inventory (licensed)",
        category="listing",
        access="licensed",
        authority_tier="commercial_listing_source",
        verification_status="unverified",
        confidence=40.0,
        writable_fields=("fsbo_listed", "fsbo_listed_at", "fsbo_asking_price", "fsbo_source_reference"),
        feature_flag="LISTING_FSBO_ENABLED",
        endpoint_env="LISTING_FSBO_ENDPOINT",
        license_required=True,
        supported_transports=("licensed_api",),
        notes=(
            "FSBO is not a public record and no government authority publishes it. This slot accepts an "
            "authorized feed the operator is licensed to consume; it never collects listings from sites whose "
            "terms forbid automated access. Seller-stated price and status are unverified by definition."
        ),
    ),
    ProviderSpec(
        id="mls_idx",
        name="MLS/IDX listing feed (licensed)",
        category="listing",
        access="licensed",
        authority_tier="commercial_listing_source",
        verification_status="partially_verified",
        confidence=75.0,
        writable_fields=("mls_listed", "mls_number", "mls_list_price", "mls_status"),
        feature_flag="LISTING_MLS_ENABLED",
        endpoint_env="LISTING_MLS_ENDPOINT",
        license_required=True,
        supported_transports=("licensed_api",),
    ),
)

PROVIDERS_BY_ID = {spec.id: spec for spec in PROVIDERS}

# A licensed provider additionally requires the operator to record the
# agreement that permits the feed, so enabling one is a deliberate act rather
# than a side effect of setting an endpoint.
LICENSE_ATTESTATION_ENV = "LISTING_LICENSE_ATTESTATION"


def _flag_enabled(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _endpoint(name: str) -> str:
    return (os.getenv(name) or "").strip()


def resolve_status(spec: ProviderSpec) -> dict[str, Any]:
    """Report a provider's runtime state without contacting it."""
    enabled = _flag_enabled(spec.feature_flag)
    endpoint = _endpoint(spec.endpoint_env)
    attested = bool((os.getenv(LICENSE_ATTESTATION_ENV) or "").strip())

    if not enabled:
        state = "disabled"
        blocker = None
    elif spec.license_required and not attested:
        state = "blocked_missing_license_attestation"
        blocker = (
            f"Set {LICENSE_ATTESTATION_ENV} to the agreement reference that authorizes this feed. "
            "Licensed inventory is not enabled by an endpoint alone."
        )
    elif not endpoint:
        state = "enabled_missing_endpoint"
        blocker = f"Set {spec.endpoint_env} to the published API endpoint."
    else:
        state = "configured"
        blocker = None

    return {
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "access": spec.access,
        "authority_tier": spec.authority_tier,
        "verification_status": spec.verification_status,
        "confidence": spec.confidence,
        "writable_fields": list(spec.writable_fields),
        "supported_transports": list(spec.supported_transports),
        "procedure": spec.procedure,
        "license_required": spec.license_required,
        "feature_flag": spec.feature_flag,
        "endpoint_env": spec.endpoint_env,
        "state": state,
        "blocker": blocker,
        "endpoint_configured": bool(endpoint),
        "notes": spec.notes,
    }


@router.get("/catalog")
def catalog(principal: Principal = Depends(get_principal)):
    statuses = [resolve_status(spec) for spec in PROVIDERS]
    return {
        "organization_id": principal.organization_id,
        "providers": statuses,
        "summary": {
            "total": len(statuses),
            "configured": sum(1 for item in statuses if item["state"] == "configured"),
            "disabled": sum(1 for item in statuses if item["state"] == "disabled"),
            "public_record": sum(1 for item in statuses if item["access"] == "public_record"),
            "licensed": sum(1 for item in statuses if item["access"] == "licensed"),
        },
        "excluded_states": sorted(EXCLUDED_STATES),
        "collection_policy": {
            "documented_apis_only": True,
            "html_scraping_supported": False,
            "access_controls_bypassed": False,
            "licensed_sources_default_disabled": True,
            "owner_review_required": True,
        },
        "boundaries": [
            "Distress facts are written only for jurisdictions the operator has explicitly configured.",
            "A jurisdiction that publishes no machine interface is reported unavailable, never harvested.",
            "FSBO and MLS are licensed inventory, not public records, and stay disabled without an attested agreement.",
            "Seller-stated listing data is unverified and may not be promoted to verified by any downstream step.",
        ],
    }


@router.get("/readiness")
def readiness(principal: Principal = Depends(get_principal)):
    """What an operator still has to do before real distress data can flow."""
    statuses = [resolve_status(spec) for spec in PROVIDERS]
    outstanding = [
        {"id": item["id"], "state": item["state"], "action": item["blocker"]}
        for item in statuses
        if item["blocker"]
    ]
    configured = [item["id"] for item in statuses if item["state"] == "configured"]
    return {
        "organization_id": principal.organization_id,
        "ready": bool(configured),
        "configured_providers": configured,
        "outstanding": outstanding,
        "next_step": (
            "Configure at least one jurisdiction endpoint to begin ingesting real distress records."
            if not configured
            else "Run a dry-run ingest for a configured provider and review the results before committing."
        ),
    }

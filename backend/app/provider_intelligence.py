from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .live_public_enrichment import _fetch_census, _one_line_address
from .models import Property
from .providers.batchdata import (
    BatchDataConfig,
    BatchDataProviderError,
    canonicalize_lookup,
    credential_status,
    lookup_property,
    verify_credentials,
)

router = APIRouter(prefix="/provider-intelligence", tags=["provider intelligence v4"])

PROVIDERS = (
    {"id":"census_geocoder","name":"US Census Geocoder","priority":100,"public":True,"credential_env":None,"required":True,"capabilities":["address_standardization","coordinates","county","tract","block"],"truth":["geography"]},
    {"id":"county_assessor","name":"County Assessor","priority":95,"public":True,"credential_env":None,"required":True,"reference_registry":True,"capabilities":["owner","parcel","assessed_value","property_characteristics"],"truth":["ownership","assessment"]},
    {"id":"county_recorder","name":"County Recorder","priority":95,"public":True,"credential_env":None,"required":True,"reference_registry":True,"capabilities":["deeds","mortgages","liens","releases"],"truth":["recorded_documents"]},
    {"id":"attom","name":"ATTOM","priority":90,"public":False,"credential_env":"ATTOM_API_KEY","required":False,"capabilities":["property","owner","mortgage","avm","foreclosure"],"truth":["licensed_property_data"]},
    {"id":"mls_idx","name":"MLS/IDX","priority":85,"public":False,"credential_env":"MLS_IDX_BASE_URL","required":False,"capabilities":["sold_comps","listings","days_on_market","price_history"],"truth":["licensed_listing_data"]},
    {"id":"batchdata","name":"BatchData MCP","priority":80,"public":False,"credential_env":"BATCHDATA_API_TOKEN","required":True,"capabilities":["property","owner","phones","emails","valuation","mortgages","liens","comparables","contact_confidence"],"truth":["licensed_property_data","licensed_owner_data","licensed_contact_data"]},
)

PUBLIC_RECORD_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id":"fl_escambia_assessor",
        "provider_id":"county_assessor",
        "state":"FL",
        "county":"Escambia",
        "name":"Escambia County Property Appraiser",
        "url":"https://escpa.org/",
        "access_mode":"official_search",
        "verification_status":"human_review_required",
    },
    {
        "id":"fl_escambia_recorder",
        "provider_id":"county_recorder",
        "state":"FL",
        "county":"Escambia",
        "name":"Escambia County Clerk Official Records",
        "url":"https://www.escambiaclerk.com/338/Official-Records",
        "search_url":"https://dory.escambiaclerk.com/LandmarkWeb1.4.6.134/search/index",
        "access_mode":"official_search",
        "verification_status":"human_review_required",
    },
)


class OrchestrationRequest(BaseModel):
    property_ids: list[int] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    commit: bool = False
    use_batchdata: bool = True
    include_contacts: bool = False


class ProviderVerificationRequest(BaseModel):
    provider_id: str


def _county_name(value: str) -> str:
    return re.sub(r"\s+(county|parish|borough|census area|municipality)$", "", value.strip(), flags=re.IGNORECASE).strip()


def jurisdiction_public_record_sources(state: str, county: str) -> list[dict[str, Any]]:
    normalized_state = state.strip().upper()
    normalized_county = _county_name(county)
    if not re.fullmatch(r"[A-Z]{2}", normalized_state):
        raise HTTPException(422, "State must be a two-letter US postal code")
    if len(normalized_county) < 2:
        raise HTTPException(422, "County or county-equivalent name is required")
    registered = [
        source for source in PUBLIC_RECORD_SOURCES
        if source["state"] == normalized_state and _county_name(source["county"]).lower() == normalized_county.lower()
    ]
    if registered:
        return registered
    base = f"{normalized_county} County {normalized_state}"
    return [
        {
            "id": f"{normalized_state.lower()}_{re.sub(r'[^a-z0-9]+', '_', normalized_county.lower()).strip('_')}_assessor_discovery",
            "provider_id": "county_assessor",
            "state": normalized_state,
            "county": normalized_county,
            "name": f"Find {normalized_county} County Assessor / Property Appraiser",
            "url": f"https://www.google.com/search?q={quote_plus('site:.gov ' + base + ' property assessor appraiser parcel search')}",
            "access_mode": "official_source_discovery",
            "verification_status": "human_review_required",
            "discovery_only": True,
        },
        {
            "id": f"{normalized_state.lower()}_{re.sub(r'[^a-z0-9]+', '_', normalized_county.lower()).strip('_')}_recorder_discovery",
            "provider_id": "county_recorder",
            "state": normalized_state,
            "county": normalized_county,
            "name": f"Find {normalized_county} County Recorder / Clerk Official Records",
            "url": f"https://www.google.com/search?q={quote_plus('site:.gov ' + base + ' recorder clerk official records deed search')}",
            "access_mode": "official_source_discovery",
            "verification_status": "human_review_required",
            "discovery_only": True,
        },
    ]


def _batchdata_configured() -> bool:
    return bool(
        (os.getenv("BATCHDATA_MCP_URL") or "").strip()
        and (os.getenv("BATCHDATA_API_TOKEN") or "").strip()
    )


def _status(
    provider: dict[str, Any],
    db: Session,
    organization_id: int,
    verify_live: bool = False,
) -> dict[str, Any]:
    env = provider["credential_env"]
    configured = True if env is None else bool((os.getenv(env) or "").strip())
    if provider["id"] == "batchdata":
        configured = _batchdata_configured()
    state = "ready" if configured else ("optional_not_configured" if not provider.get("required", True) else "blocked")
    verified = env is None
    verification: dict[str, Any] | None = None
    missing = [] if configured else ([env] if env else [])

    if provider["id"] == "batchdata":
        config = BatchDataConfig.from_env()
        connection = credential_status(config)
        configured = bool(connection["configured"])
        state = connection["state"]
        verified = False
        missing = connection["missing"]
        verification = connection
        if verify_live and config and configured:
            verification = verify_credentials(config, db, organization_id)
            state = verification["state"]
            verified = bool(verification["verified"])

    if provider.get("reference_registry"):
        matching_sources = [source for source in PUBLIC_RECORD_SOURCES if source["provider_id"] == provider["id"]]
        configured = bool(matching_sources)
        verified = False
        state = "ready_reference" if configured else "blocked"
        missing = [] if configured else ["JURISDICTION_SOURCE"]
        verification = {
            "environment":"official_public_registry",
            "source_count":len(matching_sources),
            "reason":"Official search available; property facts require human review before promotion.",
        }

    return {
        **provider,
        "configured": configured,
        "verified": verified,
        "state": state,
        "missing": missing,
        "verification": verification,
    }


def _allowed_ids(db: Session, org_id: int) -> set[int]:
    explicit = set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == org_id,
        WorkspaceEntity.entity_type == "property",
    )).all())
    leads = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == org_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())
    inherited = set(db.scalars(select(Property.id).where(Property.lead_id.in_(leads))).all()) if leads else set()
    return explicit | inherited


def _address_parts(item: Property) -> dict[str, str]:
    return {
        "street": (item.address or "").strip(),
        "city": (item.city or "").strip(),
        "state": (item.state or "").strip(),
        "zip": (item.zip_code or "").strip(),
    }


def _redact_contacts(canonical: dict[str, Any]) -> dict[str, Any]:
    contacts = canonical.get("contacts")
    count = len(contacts) if isinstance(contacts, list) else len(contacts) if isinstance(contacts, dict) else 0
    canonical["contacts"] = {
        "available": count > 0,
        "record_count": count,
        "redacted": True,
        "compliance_required": True,
    }
    return canonical


def _underwriting_inputs(canonical: dict[str, Any]) -> dict[str, Any]:
    valuation = canonical.get("valuation") or {}
    property_data = canonical.get("property") or {}
    comparables = canonical.get("comparables") or []
    return {
        "valuation_available": bool(valuation),
        "comparables_available": bool(comparables),
        "property_characteristics_available": bool(property_data),
        "arv_status": "needs_review" if valuation or comparables else "insufficient_data",
        "rehab_status": "manual_inspection_required",
        "mao_status": "blocked_until_arv_and_rehab_approved",
        "external_offer_allowed": False,
    }


@router.get("/snapshot")
def snapshot(
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    providers = sorted((_status(p, db, principal.organization_id) for p in PROVIDERS), key=lambda p: -p["priority"])
    ready = [p for p in providers if p["state"] in {"ready", "ready_verified", "ready_reference"}]
    allowed_ids = _allowed_ids(db, principal.organization_id)
    workspace_properties = list(db.scalars(select(Property).where(Property.id.in_(allowed_ids))).all()) if allowed_ids else []
    eligible_property_count = sum(
        1
        for item in workspace_properties
        if (item.state or "").upper() != "TX"
        and all((value or "").strip() for value in (item.address, item.city, item.state, item.zip_code))
    )
    return {
        "organization_id": principal.organization_id,
        "version": "4.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
        "public_record_sources": PUBLIC_RECORD_SOURCES,
        "ready_count": len(ready),
        "provider_count": len(providers),
        "eligible_property_count": eligible_property_count,
        "orchestration": {
            "strategy":"priority_then_fallback",
            "canonical_contract":True,
            "field_level_provenance":True,
            "confidence_required":True,
            "preview_first":True,
            "batchdata_mode":"server_token_mcp",
        },
        "safety": {
            "external_actions":False,
            "credentials_exposed":False,
            "texas_excluded":True,
            "owner_review_required":True,
            "contact_data_redacted_by_default":True,
            "dnc_tcpa_screening_required":True,
        },
    }


@router.get("/public-record-sources")
def public_record_sources(
    state: str,
    county: str,
    principal: Principal = Depends(require_role("manager")),
):
    sources = jurisdiction_public_record_sources(state, county)
    return {
        "state": state.strip().upper(),
        "county": _county_name(county),
        "sources": sources,
        "registered_source_count": sum(1 for source in sources if not source.get("discovery_only")),
        "human_review_required": True,
        "instruction": "Open the assessor/appraiser first, confirm the official government host and parcel owner, then use recorder/clerk records for deeds, mortgages, liens, releases, and authority.",
        "boundary": "Discovery links locate likely official systems; opening a link never verifies a property or seller authority.",
    }


@router.post("/verify")
def verify_provider(
    payload: ProviderVerificationRequest,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    provider = next((item for item in PROVIDERS if item["id"] == payload.provider_id), None)
    if not provider:
        raise HTTPException(404, "Provider not found")
    status = _status(provider, db, principal.organization_id, verify_live=True)
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": status,
        "safe_check_only": True,
        "credentials_exposed": False,
    }


@router.post("/orchestrate")
def orchestrate(
    payload: OrchestrationRequest,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    allowed = _allowed_ids(db, principal.organization_id)
    requested = payload.property_ids or sorted(allowed)
    selected = [property_id for property_id in requested if property_id in allowed][:payload.limit]
    properties = list(db.scalars(select(Property).where(Property.id.in_(selected)).order_by(Property.id)).all()) if selected else []

    results: list[dict[str, Any]] = []
    committed = 0
    skipped = 0
    config = BatchDataConfig.from_env() if payload.use_batchdata else None

    for item in properties:
        if (item.state or "").upper() == "TX":
            results.append({"property_id":item.id,"status":"excluded","reason":"Texas excluded"})
            skipped += 1
            continue

        address = _one_line_address(item)
        canonical: dict[str, Any] = {}
        providers_used: list[str] = []
        provider_errors: list[dict[str, Any]] = []

        census_match = _fetch_census(address)
        if census_match:
            providers_used.append("census_geocoder")
            canonical["geography"] = census_match
            canonical.setdefault("field_provenance", {})["geography"] = {
                "provider_id":"census_geocoder",
                "observed_at":datetime.now(timezone.utc).isoformat(),
                "confidence":0.95,
            }

        state = (item.state or "").strip().upper()
        census_county = str(((census_match or {}).get("county") or {}).get("NAME") or "")
        public_sources = jurisdiction_public_record_sources(state, census_county) if state and census_county else []
        if public_sources:
            canonical["public_record_sources"] = public_sources
            canonical["public_record_verification"] = {
                "status":"human_review_required",
                "ownership_verified":False,
                "recorded_documents_verified":False,
                "instruction":"Search the official assessor first, then confirm deeds and liens in Official Records.",
            }

        if config and payload.use_batchdata:
            try:
                batch_result = lookup_property(config, db, principal.organization_id, _address_parts(item))
                batch_canonical = canonicalize_lookup(batch_result)
                if not payload.include_contacts:
                    batch_canonical = _redact_contacts(batch_canonical)
                providers_used.append("batchdata")
                for key, value in batch_canonical.items():
                    if key == "field_provenance":
                        canonical.setdefault("field_provenance", {}).update(value)
                    else:
                        canonical[key] = value
            except BatchDataProviderError as exc:
                provider_errors.append({
                    "provider_id":"batchdata",
                    "state":exc.state,
                    "http_status":exc.http_status,
                    "reason":str(exc),
                })

        if not providers_used:
            results.append({
                "property_id":item.id,
                "status":"no_match",
                "address":address,
                "providers_tried":["census_geocoder", "batchdata" if payload.use_batchdata else None],
                "provider_errors":provider_errors,
            })
            skipped += 1
            continue

        canonical["underwriting_inputs"] = _underwriting_inputs(canonical)
        confidence_values = [
            source.get("confidence", 0.0)
            for source in canonical.get("field_provenance", {}).values()
            if isinstance(source, dict)
        ]
        confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0

        if payload.commit:
            geography = canonical.get("geography") or {}
            if geography.get("latitude") is not None:
                item.latitude = float(geography["latitude"])
            if geography.get("longitude") is not None:
                item.longitude = float(geography["longitude"])
            db.add(CrmActivity(
                organization_id=principal.organization_id,
                user_id=getattr(principal, "user_id", None),
                lead_id=item.lead_id,
                activity_type="provider_intelligence_v4_enriched",
                summary="Provider Intelligence v4 created a governed canonical enrichment record",
                metadata_json={
                    "version":"4.0",
                    "providers":providers_used,
                    "field_provenance":canonical.get("field_provenance", {}),
                    "confidence":confidence,
                    "underwriting_inputs":canonical.get("underwriting_inputs", {}),
                    "contact_data_committed":False,
                    "external_actions":False,
                    "owner_review_required":True,
                },
            ))
            committed += 1

        results.append({
            "property_id":item.id,
            "status":"committed" if payload.commit else "preview",
            "address":address,
            "canonical":canonical,
            "providers_used":providers_used,
            "provider_errors":provider_errors,
            "confidence":confidence,
            "owner_review_required":True,
            "external_actions":False,
        })

    if payload.commit:
        db.commit()

    return {
        "version":"4.0",
        "processed_count":len(properties),
        "committed_count":committed,
        "skipped_count":skipped,
        "commit":payload.commit,
        "results":results,
        "truth_contract":{
            "ownership_verified":False,
            "valuation_verified":False,
            "contact_verified":False,
            "geography_verified":True,
            "provider_data_requires_owner_review":True,
            "external_actions":False,
        },
    }

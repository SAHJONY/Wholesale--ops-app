from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

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
    lookup_property,
    verify_credentials,
)

router = APIRouter(prefix="/provider-intelligence", tags=["provider intelligence v3"])

PROVIDERS = (
    {"id":"census_geocoder","name":"US Census Geocoder","priority":100,"public":True,"credential_env":None,"capabilities":["address_standardization","coordinates","county","tract","block"],"truth":["geography"]},
    {"id":"county_assessor","name":"County Assessor","priority":95,"public":True,"credential_env":"COUNTY_ASSESSOR_BASE_URL","capabilities":["owner","parcel","assessed_value","property_characteristics"],"truth":["ownership","assessment"]},
    {"id":"county_recorder","name":"County Recorder","priority":95,"public":True,"credential_env":"COUNTY_RECORDER_BASE_URL","capabilities":["deeds","mortgages","liens","releases"],"truth":["recorded_documents"]},
    {"id":"attom","name":"ATTOM","priority":90,"public":False,"credential_env":"ATTOM_API_KEY","capabilities":["property","owner","mortgage","avm","foreclosure"],"truth":["licensed_property_data"]},
    {"id":"mls_idx","name":"MLS/IDX","priority":85,"public":False,"credential_env":"MLS_IDX_BASE_URL","capabilities":["sold_comps","listings","days_on_market","price_history"],"truth":["licensed_listing_data"]},
    {"id":"batchdata","name":"BatchData","priority":80,"public":False,"credential_env":"BATCHDATA_API_KEY","capabilities":["property","owner","phones","emails","valuation","mortgages","liens","comparables","contact_confidence"],"truth":["licensed_property_data","licensed_owner_data","licensed_contact_data"]},
)


class OrchestrationRequest(BaseModel):
    property_ids: list[int] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    commit: bool = False
    use_batchdata: bool = True
    include_contacts: bool = False


class ProviderVerificationRequest(BaseModel):
    provider_id: str


def _batchdata_configured() -> bool:
    return bool((os.getenv("BATCHDATA_SANDBOX_API_KEY") or os.getenv("BATCHDATA_API_KEY") or "").strip())


def _status(provider: dict[str, Any], verify_live: bool = False) -> dict[str, Any]:
    env = provider["credential_env"]
    configured = True if env is None else bool((os.getenv(env) or "").strip())
    if provider["id"] == "batchdata":
        configured = _batchdata_configured()
    state = "ready" if configured else "blocked"
    verified = env is None
    verification: dict[str, Any] | None = None
    missing = [] if configured else ([env] if env else [])

    if provider["id"] == "batchdata" and configured:
        config = BatchDataConfig.from_env()
        if verify_live and config:
            verification = verify_credentials(config)
            state = verification["state"]
            verified = bool(verification["verified"])
        else:
            state = "configured_unverified"
            verified = False
        if config and not config.lookup_url:
            missing = ["BATCHDATA_PROPERTY_LOOKUP_URL"]

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
def snapshot(principal: Principal = Depends(require_role("manager"))):
    providers = sorted((_status(p, verify_live=p["id"] == "batchdata") for p in PROVIDERS), key=lambda p: -p["priority"])
    ready = [p for p in providers if p["state"] in {"ready", "ready_verified"}]
    return {
        "organization_id": principal.organization_id,
        "version": "3.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
        "ready_count": len(ready),
        "provider_count": len(providers),
        "orchestration": {
            "strategy":"priority_then_fallback",
            "canonical_contract":True,
            "field_level_provenance":True,
            "confidence_required":True,
            "preview_first":True,
            "batchdata_mode":"sandbox" if (os.getenv("BATCHDATA_SANDBOX_API_KEY") or "").strip() else "production",
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


@router.post("/verify")
def verify_provider(payload: ProviderVerificationRequest, principal: Principal = Depends(require_role("manager"))):
    provider = next((item for item in PROVIDERS if item["id"] == payload.provider_id), None)
    if not provider:
        raise HTTPException(404, "Provider not found")
    status = _status(provider, verify_live=True)
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

        if config and payload.use_batchdata:
            try:
                batch_result = lookup_property(config, _address_parts(item))
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
                activity_type="provider_intelligence_v3_enriched",
                summary="Provider Intelligence v3 created a governed canonical enrichment record",
                metadata_json={
                    "version":"3.0",
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
        "version":"3.0",
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

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .live_public_enrichment import _fetch_census, _one_line_address
from .models import Property

router = APIRouter(prefix="/provider-intelligence", tags=["provider intelligence v2"])

PROVIDERS = (
    {"id":"census_geocoder","name":"US Census Geocoder","priority":100,"public":True,"credential_env":None,"capabilities":["address_standardization","coordinates","county","tract","block"],"truth":["geography"]},
    {"id":"county_assessor","name":"County Assessor","priority":95,"public":True,"credential_env":"COUNTY_ASSESSOR_BASE_URL","capabilities":["owner","parcel","assessed_value","property_characteristics"],"truth":["ownership","assessment"]},
    {"id":"county_recorder","name":"County Recorder","priority":95,"public":True,"credential_env":"COUNTY_RECORDER_BASE_URL","capabilities":["deeds","mortgages","liens","releases"],"truth":["recorded_documents"]},
    {"id":"attom","name":"ATTOM","priority":90,"public":False,"credential_env":"ATTOM_API_KEY","capabilities":["property","owner","mortgage","avm","foreclosure"],"truth":["licensed_property_data"]},
    {"id":"mls_idx","name":"MLS/IDX","priority":85,"public":False,"credential_env":"MLS_IDX_BASE_URL","capabilities":["sold_comps","listings","days_on_market","price_history"],"truth":["licensed_listing_data"]},
    {"id":"batchdata","name":"BatchData","priority":80,"public":False,"credential_env":"BATCHDATA_API_KEY","capabilities":["phones","emails","contact_confidence"],"truth":["licensed_contact_data"]},
)

BATCHDATA_VERIFY_URL = (os.getenv("BATCHDATA_VERIFY_URL") or "https://api.batchdata.com").strip()


class OrchestrationRequest(BaseModel):
    property_ids: list[int] | None = None
    limit: int = Field(default=25, ge=1, le=100)
    commit: bool = False


class ProviderVerificationRequest(BaseModel):
    provider_id: str


def _classify_verification_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ready_verified"
    if status_code in {401, 403}:
        return "invalid_credentials"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "unavailable"
    return "configured_unverified"


def _verify_batchdata() -> dict[str, Any]:
    key = (os.getenv("BATCHDATA_API_KEY") or "").strip()
    if not key:
        return {"state":"blocked","verified":False,"reason":"BATCHDATA_API_KEY missing"}
    if not BATCHDATA_VERIFY_URL.startswith("https://"):
        return {"state":"unavailable","verified":False,"reason":"BATCHDATA_VERIFY_URL must use HTTPS"}
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            response = client.get(
                BATCHDATA_VERIFY_URL,
                headers={"Authorization": f"Bearer {key}", "X-API-Key": key, "Accept": "application/json"},
            )
        state = _classify_verification_status(response.status_code)
        return {
            "state": state,
            "verified": state == "ready_verified",
            "http_status": response.status_code,
            "reason": None if state == "ready_verified" else state.replace("_", " "),
        }
    except httpx.TimeoutException:
        return {"state":"unavailable","verified":False,"reason":"verification timeout"}
    except httpx.HTTPError as exc:
        return {"state":"unavailable","verified":False,"reason":type(exc).__name__}


def _status(provider: dict[str, Any], verify_live: bool = False) -> dict[str, Any]:
    env = provider["credential_env"]
    configured = True if env is None else bool((os.getenv(env) or "").strip())
    state = "ready" if configured else "blocked"
    verified = env is None
    verification: dict[str, Any] | None = None
    if provider["id"] == "batchdata" and configured:
        if verify_live:
            verification = _verify_batchdata()
            state = verification["state"]
            verified = bool(verification["verified"])
        else:
            state = "configured_unverified"
            verified = False
    return {
        **provider,
        "configured": configured,
        "verified": verified,
        "state": state,
        "missing": [] if configured else [env],
        "verification": verification,
    }


def _allowed_ids(db: Session, org_id: int) -> set[int]:
    explicit = set(db.scalars(select(WorkspaceEntity.entity_id).where(WorkspaceEntity.organization_id==org_id, WorkspaceEntity.entity_type=="property")).all())
    leads = list(db.scalars(select(WorkspaceEntity.entity_id).where(WorkspaceEntity.organization_id==org_id, WorkspaceEntity.entity_type=="lead")).all())
    inherited = set(db.scalars(select(Property.id).where(Property.lead_id.in_(leads))).all()) if leads else set()
    return explicit | inherited


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(require_role("manager"))):
    providers = sorted((_status(p, verify_live=p["id"] == "batchdata") for p in PROVIDERS), key=lambda p: -p["priority"])
    ready = [p for p in providers if p["state"] in {"ready", "ready_verified"}]
    return {
        "organization_id": principal.organization_id,
        "version": "2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
        "ready_count": len(ready),
        "provider_count": len(providers),
        "orchestration": {"strategy":"priority_then_fallback","canonical_contract":True,"provenance_required":True,"confidence_required":True},
        "safety": {"external_actions":False,"credentials_exposed":False,"texas_excluded":True,"owner_review_required":True},
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
def orchestrate(payload: OrchestrationRequest, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    allowed = _allowed_ids(db, principal.organization_id)
    requested = payload.property_ids or sorted(allowed)
    selected = [i for i in requested if i in allowed][:payload.limit]
    properties = list(db.scalars(select(Property).where(Property.id.in_(selected)).order_by(Property.id)).all()) if selected else []
    results=[]; committed=0; skipped=0
    for item in properties:
        if (item.state or "").upper()=="TX":
            results.append({"property_id":item.id,"status":"excluded","reason":"Texas excluded"}); skipped+=1; continue
        address = _one_line_address(item)
        match = _fetch_census(address)
        if not match:
            results.append({"property_id":item.id,"status":"no_match","address":address,"providers_tried":["census_geocoder"]}); skipped+=1; continue
        if payload.commit:
            if match.get("latitude") is not None: item.latitude=float(match["latitude"])
            if match.get("longitude") is not None: item.longitude=float(match["longitude"])
            db.add(CrmActivity(organization_id=principal.organization_id,user_id=getattr(principal,"user_id",None),lead_id=item.lead_id,activity_type="provider_intelligence_enriched",summary="Provider Intelligence Layer enriched property geography",metadata_json={"version":"2.1","providers":["census_geocoder"],"provenance":{"source":"US Census Geocoder","observed_at":datetime.now(timezone.utc).isoformat()},"confidence":0.95,"truth_scope":["geography"],"limitations":["not ownership","not valuation","not contact data"]}))
            committed+=1
        results.append({"property_id":item.id,"status":"committed" if payload.commit else "preview","address":address,"canonical":{"geography":match},"providers_used":["census_geocoder"],"confidence":0.95,"provenance":[{"provider_id":"census_geocoder","observed_at":datetime.now(timezone.utc).isoformat()}]})
    if payload.commit: db.commit()
    return {"version":"2.1","processed_count":len(properties),"committed_count":committed,"skipped_count":skipped,"commit":payload.commit,"results":results,"truth_contract":{"ownership_verified":False,"valuation_verified":False,"contact_verified":False,"geography_verified":True}}

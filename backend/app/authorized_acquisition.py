from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .autonomous_property_acquisition import acquisition_feed_status, run_autonomous_property_acquisition
from .database import get_db

router = APIRouter(prefix="/authorized-acquisition", tags=["authorized acquisition discovery"])


def _pipeline_status() -> dict:
    feed = acquisition_feed_status()
    missing: list[str] = []
    if not feed["enabled"]:
        missing.append("Set ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION=true or configure ATTOM_API_KEY for auto-enable")
    if not feed["configured"]:
        missing.append("Configure ATTOM_API_KEY or AUTONOMOUS_PROPERTY_FEED_URL=https://...")
    if feed["provider_mode"] == "external_https" and not feed["secure"]:
        missing.append("AUTONOMOUS_PROPERTY_FEED_URL must use HTTPS")
    return {
        "feed": feed,
        "ready": bool(feed["enabled"] and feed["configured"] and feed["secure"]),
        "missing_configuration": missing,
        "pipeline": [
            "authorized provider or HTTPS property feed",
            "provider-neutral normalization",
            "tenant-safe address deduplication",
            "property-candidate review queue",
            "public-record owner/deed verification",
            "individual-owner screening",
            "distress and comp-backed underwriting",
            "Deal Factory promotion after evidence gates",
        ],
        "safety": {
            "review_only": True,
            "owner_identity_from_feed_is_verified": False,
            "contact_enrichment_automatic": False,
            "outreach_allowed": False,
            "autonomous_contracts": False,
            "autonomous_financial_commitments": False,
        },
    }


@router.get("/status")
def status(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc),
        **_pipeline_status(),
    }


@router.post("/run")
async def run_authorized_feed(
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    state = _pipeline_status()
    if not state["ready"]:
        raise HTTPException(
            503,
            {
                "message": "Authorized property feed is not ready",
                "missing_configuration": state["missing_configuration"],
                "safety": state["safety"],
            },
        )
    try:
        result = await run_autonomous_property_acquisition(db, principal)
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"Authorized property feed failed: {type(exc).__name__}") from exc

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="authorized_property_feed_run",
        summary="Authorized property feed completed in review-only mode",
        metadata_json={
            "source": result.get("source"),
            "provider_mode": result.get("provider_mode"),
            "received": result.get("received", 0),
            "created": result.get("created", 0),
            "updated": result.get("updated", 0),
            "duplicate": result.get("duplicate", 0),
            "rejected": result.get("rejected", 0),
            "review_only": True,
            "outreach_allowed": False,
        },
    ))
    db.commit()
    return {
        **result,
        "mode": "authorized_review_only",
        "owner_verification_required": True,
        "outreach_allowed": False,
        "next_action": "Review property candidates and verify owner/deed evidence before underwriting or outreach.",
    }

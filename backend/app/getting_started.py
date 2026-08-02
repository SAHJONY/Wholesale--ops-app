"""An ordered next-step view over the console's 31 routes.

The owner console presents every capability as an equally-weighted door. That
is fine once you know the system and unusable before you do: nothing indicates
which of the thirty-one pages matters right now, or which are inert until
something earlier is done.

This computes the sequence from actual workspace state rather than a static
tour. Steps are dependency-ordered, so a step whose prerequisite is unmet
reports `blocked` with the reason instead of appearing as an equal option --
configuring a county feed before any property exists writes nothing, and
presenting it as available wastes the operator's time.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import WorkspaceEntity
from .database import get_db
from .distress_ingest import load_jurisdictions
from .intelligence_models import IntelligenceFact
from .lead_verification import enforcement_enabled
from .models import Property

router = APIRouter(prefix="/getting-started", tags=["guided setup"])

# Credential-gated integrations, mirroring the go-live blocker list. Kept here
# so the guide can say which are outstanding without a second round trip.
CREDENTIAL_ENVS: dict[str, str] = {
    "Property data provider": "ATTOM_API_KEY",
    "Contact enrichment": "BATCHDATA_API_KEY",
    "Seller communications": "BLAND_API_KEY",
    "Contract execution": "DOCUSEAL_API_KEY",
    "Transactional email": "SMTP_USER",
}


def _count(db: Session, organization_id: int, entity_type: str) -> int:
    return db.scalar(select(func.count(WorkspaceEntity.id)).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )) or 0


def _verified_property_count(db: Session, organization_id: int) -> int:
    property_ids = set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
    )).all())
    if not property_ids:
        return 0
    rows = db.scalars(select(Property).where(Property.id.in_(property_ids))).all()
    with_coordinate = {row.id for row in rows if row.latitude is not None and row.longitude is not None}
    if not with_coordinate:
        return 0
    verified = db.scalars(select(IntelligenceFact.entity_id).where(
        IntelligenceFact.organization_id == organization_id,
        IntelligenceFact.entity_type == "property",
        IntelligenceFact.entity_id.in_(with_coordinate),
        IntelligenceFact.field_name == "normalized_address",
        IntelligenceFact.verification_status == "verified",
    )).all()
    return len(set(verified))


def _missing_credentials() -> list[str]:
    return [name for name, env in CREDENTIAL_ENVS.items() if not (os.getenv(env) or "").strip()]


def _step(
    step_id: str,
    title: str,
    why: str,
    route: str,
    done: bool,
    detail: str,
    blocked_by: str | None = None,
) -> dict[str, Any]:
    if done:
        status = "done"
    elif blocked_by:
        status = "blocked"
    else:
        status = "todo"
    return {
        "id": step_id,
        "title": title,
        "why": why,
        "route": route,
        "status": status,
        "detail": detail,
        "blocked_by": blocked_by,
    }


@router.get("/next-steps")
def next_steps(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    buyers = _count(db, principal.organization_id, "buyer")
    properties = _count(db, principal.organization_id, "property")
    verified = _verified_property_count(db, principal.organization_id)

    try:
        jurisdictions = len(load_jurisdictions())
        jurisdiction_error = None
    except Exception as exc:  # a malformed registry must not break the guide
        jurisdictions, jurisdiction_error = 0, str(getattr(exc, "detail", exc))

    missing_credentials = _missing_credentials()

    steps = [
        _step(
            "buyers",
            "Build the cash-buyer network",
            "Without an end buyer an assignment has nowhere to go, so this gates everything downstream.",
            "/owner/buyer-intake",
            done=buyers > 0,
            detail=f"{buyers} buyer{'' if buyers == 1 else 's'} on file."
            if buyers else "No buyers yet. Add the buyers you already work with.",
        ),
        _step(
            "properties",
            "Load candidate properties",
            "Verification and distress matching both operate on properties already in the workspace.",
            "/owner/data-intake",
            done=properties > 0,
            detail=f"{properties} propert{'y' if properties == 1 else 'ies'} on file."
            if properties else "No properties yet. Import addresses through data intake.",
        ),
        _step(
            "verify",
            "Verify properties against public records",
            "A lead cannot be actioned until its address resolves to a real, locatable place.",
            "/owner/lead-verification",
            done=properties > 0 and verified == properties,
            detail=(
                f"{verified} of {properties} verified."
                if properties else "Nothing to verify yet."
            ),
            blocked_by=None if properties else "Load candidate properties first.",
        ),
        _step(
            "markets",
            "Rank your markets",
            "Scores your ZIPs against buyer depth and liquidity so effort goes where you can actually assign.",
            "/owner/markets",
            done=buyers > 0 and properties > 0,
            detail="Ranking works as soon as buyers carry ZIP coverage."
            if buyers else "Needs buyers with ZIP coverage.",
            blocked_by=None if buyers else "Add cash buyers first.",
        ),
        _step(
            "jurisdictions",
            "Configure a county distress feed",
            "Tax delinquency, code violations and foreclosure records are what surface motivated sellers.",
            "/owner/provider-activation",
            done=jurisdictions > 0,
            detail=(
                f"Registry error: {jurisdiction_error}" if jurisdiction_error
                else f"{jurisdictions} jurisdiction{'' if jurisdictions == 1 else 's'} configured."
                if jurisdictions else "No jurisdictions configured yet."
            ),
            blocked_by=None if properties else "Load candidate properties first.",
        ),
        _step(
            "credentials",
            "Provision integration credentials",
            "Outreach, contracts and enrichment each need an account before the system can act.",
            "/owner/go-live",
            done=not missing_credentials,
            detail=(
                f"Outstanding: {', '.join(missing_credentials)}."
                if missing_credentials else "All tracked credentials present."
            ),
        ),
    ]

    done = [s for s in steps if s["status"] == "done"]
    actionable = [s for s in steps if s["status"] == "todo"]
    blocked = [s for s in steps if s["status"] == "blocked"]

    return {
        "organization_id": principal.organization_id,
        "summary": {
            "total_steps": len(steps),
            "done": len(done),
            "actionable": len(actionable),
            "blocked": len(blocked),
            "percent_complete": round(len(done) / len(steps) * 100, 1),
        },
        # The point of the endpoint: what to do next, not everything you could do.
        "next": actionable[0] if actionable else None,
        "steps": steps,
        "enforcement": {
            "verified_leads_required": enforcement_enabled(),
        },
        "note": (
            "Steps are ordered by dependency. A blocked step is not available yet; doing it out of "
            "order would write nothing."
        ),
    }

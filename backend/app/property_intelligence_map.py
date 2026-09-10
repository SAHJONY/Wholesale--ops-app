from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import WorkspaceEntity
from .database import get_db
from .models import Deal, Lead, Property

router = APIRouter(prefix="/property-intelligence", tags=["property intelligence map"])

SFR_TYPES = {"single_family", "single-family", "single family", "sfr"}


def _linked_property_ids(db: Session, organization_id: int) -> set[int]:
    explicit = set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "property",
    )).all())
    lead_ids = set(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all())
    inherited = set(db.scalars(select(Property.id).where(Property.lead_id.in_(lead_ids))).all()) if lead_ids else set()
    return explicit | inherited


def _signal_summary(item: Property) -> tuple[list[str], float | None]:
    signal_types: set[str] = set()
    confidence: float | None = None
    for signal in item.distress_signals if isinstance(item.distress_signals, list) else []:
        if not isinstance(signal, dict):
            continue
        signal_type = str(signal.get("type") or signal.get("category") or "").strip().lower()
        if signal_type:
            signal_types.add(signal_type[:80])
        raw_confidence = signal.get("confidence")
        if isinstance(raw_confidence, (int, float)):
            normalized = float(raw_confidence)
            if normalized > 1:
                normalized /= 100
            confidence = max(0.0, min(normalized, 1.0))
    return sorted(signal_types), confidence


@router.get("/globe")
def property_globe(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    property_ids = _linked_property_ids(db, principal.organization_id)
    properties = list(db.scalars(
        select(Property).where(Property.id.in_(property_ids)).order_by(Property.id.desc())
    ).all()) if property_ids else []
    included = [
        item for item in properties
        if (item.state or "").strip().upper() != "TX"
        and (item.property_type or "").strip().lower() in SFR_TYPES
    ]
    lead_ids = [item.lead_id for item in included]
    leads = {
        item.id: item for item in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()
    } if lead_ids else {}
    included_ids = [item.id for item in included]
    deals = {
        item.property_id: item for item in db.scalars(select(Deal).where(Deal.property_id.in_(included_ids))).all()
    } if included_ids else {}

    points = []
    for item in included:
        lead = leads.get(item.lead_id)
        deal = deals.get(item.id)
        signal_types, confidence = _signal_summary(item)
        mapped = item.latitude is not None and item.longitude is not None
        points.append({
            "property_id": item.id,
            "lead_id": item.lead_id,
            "address": item.address,
            "city": item.city,
            "state": item.state,
            "zip_code": item.zip_code,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "mapped": mapped,
            "property_type": item.property_type,
            "status": lead.status if lead else "unknown",
            "motivation_score": lead.motivation_score if lead else 0,
            "distress_score": lead.distress_score if lead else 0,
            "equity_score": lead.equity_score if lead else 0,
            "signal_types": signal_types,
            "confidence": confidence,
            "arv": item.arv,
            "repairs": item.repairs,
            "mao": item.mao,
            "deal_id": deal.id if deal else None,
            "deal_stage": deal.stage if deal else None,
            "projected_assignment_fee": deal.projected_assignment_fee if deal else None,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": principal.organization_id,
        "summary": {
            "properties": len(points),
            "mapped": sum(1 for point in points if point["mapped"]),
            "unmapped": sum(1 for point in points if not point["mapped"]),
            "active_deals": sum(1 for point in points if point["deal_id"] is not None),
            "excluded_texas": sum(1 for item in properties if (item.state or "").strip().upper() == "TX"),
            "excluded_non_sfr": sum(
                1 for item in properties
                if (item.state or "").strip().upper() != "TX"
                and (item.property_type or "").strip().lower() not in SFR_TYPES
            ),
        },
        "properties": points,
        "governance": {
            "contact_data_exposed": False,
            "owner_identity_exposed": False,
            "external_actions_allowed": False,
            "texas_excluded": True,
            "single_family_only": True,
            "authoritative_verification_required": True,
        },
    }

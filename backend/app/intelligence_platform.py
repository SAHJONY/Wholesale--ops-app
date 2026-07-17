from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .database import get_db
from .event_bus import emit_event
from .intelligence_models import CanonicalEntity, IntelligenceConflict, IntelligenceFact

router = APIRouter(prefix="/intelligence-platform", tags=["enterprise intelligence platform"])
ENTITY_TYPES = {"property", "seller", "buyer"}
VERIFICATION_STATES = {"unverified", "partially_verified", "verified", "disputed", "stale"}


def _entity(db: Session, principal: Principal, entity_type: str, entity_id: int) -> CanonicalEntity:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(422, "Entity type must be property, seller, or buyer")
    row = db.scalar(select(CanonicalEntity).where(
        CanonicalEntity.organization_id == principal.organization_id,
        CanonicalEntity.entity_type == entity_type,
        CanonicalEntity.entity_id == entity_id,
    ))
    if not row:
        row = CanonicalEntity(organization_id=principal.organization_id, entity_type=entity_type, entity_id=entity_id)
        db.add(row)
        db.flush()
    return row

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .database import Base, engine, get_db

router = APIRouter(prefix="/national-intelligence", tags=["national property intelligence network"])


def _module():
    from . import national_intelligence as implementation

    # Register and create intelligence tables before their first query. This is
    # idempotent and preserves existing data.
    Base.metadata.create_all(bind=engine)
    return implementation


def _setup_snapshot(detail: str) -> dict:
    return {
        "generated_at": datetime.utcnow(),
        "status": "setup",
        "detail": detail,
        "summary": {
            "properties": 0,
            "high_priority": 0,
            "ownership_verified": 0,
            "projected_assignment_fees": 0,
            "average_opportunity_score": 0,
        },
        "properties": [],
        "markets": [],
        "runs": [],
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    try:
        return _module().snapshot(principal=principal, db=db)
    except Exception as exc:
        db.rollback()
        return _setup_snapshot(
            f"National Intelligence is in setup mode: {type(exc).__name__}. Deploy the latest backend and verify database connectivity."
        )


@router.post("/refresh")
def refresh(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        return _module().refresh(payload=payload, principal=principal, db=db)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"National Intelligence database objects are not ready: {type(exc).__name__}. Redeploy the latest backend.",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"National Intelligence refresh failed safely: {type(exc).__name__}.",
        ) from exc


@router.get("/properties/{property_id}")
def property_detail(
    property_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    try:
        return _module().property_detail(property_id=property_id, principal=principal, db=db)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"Property intelligence database objects are not ready: {type(exc).__name__}.",
        ) from exc

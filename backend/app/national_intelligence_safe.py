from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .database import get_db

router = APIRouter(prefix="/national-intelligence", tags=["national property intelligence network"])


def _module():
    try:
        from . import national_intelligence as implementation
        return implementation
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"National Intelligence service failed to initialize: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _module().snapshot(principal=principal, db=db)


@router.post("/refresh")
def refresh(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    return _module().refresh(payload=payload, principal=principal, db=db)


@router.get("/properties/{property_id}")
def property_detail(
    property_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    return _module().property_detail(property_id=property_id, principal=principal, db=db)

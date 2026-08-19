from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import WorkspaceEntity
from .database import get_db
from .models import Buyer

router = APIRouter(prefix="/buyer-directory", tags=["buyer directory"])


@router.get("")
def directory(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    buyer_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "buyer",
    )).all())
    if not buyer_ids:
        return {"count": 0, "buyers": []}

    buyers = db.scalars(
        select(Buyer).where(Buyer.id.in_(buyer_ids)).order_by(
            Buyer.proof_of_funds_verified.desc(),
            Buyer.reliability_score.desc(),
            Buyer.name.asc(),
        )
    ).all()
    return {
        "count": len(buyers),
        "buyers": [
            {
                "id": buyer.id,
                "name": buyer.name,
                "company": buyer.company,
                "buyer_type": buyer.buyer_type,
                "phone": buyer.phone,
                "email": buyer.email,
                "zip_codes": buyer.zip_codes or [],
                "asset_types": buyer.asset_types or [],
                "min_price": buyer.min_price,
                "max_price": buyer.max_price,
                "max_rehab": buyer.max_rehab,
                "closing_days": buyer.closing_days,
                "proof_of_funds_verified": buyer.proof_of_funds_verified,
                "reliability_score": buyer.reliability_score,
                "response_rate": buyer.response_rate,
            }
            for buyer in buyers
        ],
    }

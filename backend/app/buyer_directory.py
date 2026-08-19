from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .auth_models import WorkspaceEntity
from .cash_buyer_models import CashBuyerCandidate
from .database import get_db
from .distress_ingest import load_jurisdictions
from .models import Buyer

router = APIRouter(prefix="/buyer-directory", tags=["buyer directory"])


def _buyer_intelligence_status() -> dict:
    try:
        sources = [source for source in load_jurisdictions() if source.category == "cash_purchase_deed"]
        states = sorted({source.state for source in sources})
        counties = sorted({f"{source.county}, {source.state}" for source in sources})
        return {
            "configured_sources": len(sources),
            "states": states,
            "counties": counties,
            "ready": bool(sources),
            "error": None,
        }
    except Exception as exc:
        return {
            "configured_sources": 0,
            "states": [],
            "counties": [],
            "ready": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.get("")
def directory(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    buyer_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "buyer",
    )).all())
    buyers = []
    if buyer_ids:
        buyers = db.scalars(
            select(Buyer).where(Buyer.id.in_(buyer_ids)).order_by(
                Buyer.proof_of_funds_verified.desc(),
                Buyer.reliability_score.desc(),
                Buyer.name.asc(),
            )
        ).all()

    candidate_count = db.scalar(select(func.count(CashBuyerCandidate.id)).where(
        CashBuyerCandidate.organization_id == principal.organization_id,
    )) or 0
    cash_confirmed_candidates = db.scalar(select(func.count(CashBuyerCandidate.id)).where(
        CashBuyerCandidate.organization_id == principal.organization_id,
        CashBuyerCandidate.cash_evidence == "confirmed",
    )) or 0
    promoted_candidates = db.scalar(select(func.count(CashBuyerCandidate.id)).where(
        CashBuyerCandidate.organization_id == principal.organization_id,
        CashBuyerCandidate.promoted_buyer_id.is_not(None),
    )) or 0

    localized = sum(1 for buyer in buyers if buyer.zip_codes)
    national_or_unscoped = sum(1 for buyer in buyers if not buyer.zip_codes)
    pof_verified = sum(1 for buyer in buyers if buyer.proof_of_funds_verified)

    return {
        "count": len(buyers),
        "summary": {
            "total_buyers": len(buyers),
            "localized_buyers": localized,
            "national_or_unscoped_buyers": national_or_unscoped,
            "proof_of_funds_verified": pof_verified,
            "cash_buyer_candidates": int(candidate_count),
            "cash_evidence_confirmed_candidates": int(cash_confirmed_candidates),
            "autonomously_promoted_candidates": int(promoted_candidates),
        },
        "operating_mode": {
            "mode": "buyers_first_parallel",
            "strategy": "reverse_deals_plus_continuous_acquisition",
            "scope": "nationwide",
            "lead_acquisition_phase": "continuous_parallel_buyer_box_driven",
            "property_acquisition_paused": False,
            "buyer_box_priority": "verified_pof_then_local_zip_asset_price_rehab_close_speed",
            "pof_policy": "documentary_verification_only_never_infer",
        },
        "buyer_intelligence": _buyer_intelligence_status(),
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

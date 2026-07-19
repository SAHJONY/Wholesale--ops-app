from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Buyer, Deal, Lead, Property

router = APIRouter(prefix="/test-deal", tags=["test deal rehearsal"])


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _evaluate(db: Session, principal: Principal, lead_id: int | None = None) -> dict:
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    if not lead_ids:
        return {"status": "blocked", "score": 0, "checks": [], "reason": "No tenant-linked leads are available."}

    selected_id = lead_id if lead_id in lead_ids else lead_ids[0]
    lead = db.get(Lead, selected_id)
    if not lead or not lead.property:
        raise HTTPException(404, "Lead or property not found in this workspace")
    property_row: Property = lead.property
    if property_row.state.upper() == "TX":
        raise HTTPException(409, "Texas properties are excluded from SAHJONY wholesale workflows")

    buyer_ids = _linked_ids(db, principal.organization_id, "buyer")
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    matching_buyers = [buyer for buyer in buyers if property_row.zip_code in (buyer.zip_codes or [])]
    verified_buyers = [buyer for buyer in matching_buyers if buyer.proof_of_funds_verified]

    deal_ids = _linked_ids(db, principal.organization_id, "deal")
    existing_deal = db.scalar(select(Deal).where(Deal.id.in_(deal_ids), Deal.property_id == property_row.id)) if deal_ids else None

    checks = [
        {"name": "Tenant ownership", "ready": True, "detail": f"Lead #{lead.id} is linked to this workspace."},
        {"name": "Texas exclusion", "ready": property_row.state.upper() != "TX", "detail": f"State: {property_row.state.upper()}"},
        {"name": "Underwriting inputs", "ready": all(value is not None for value in [property_row.arv, property_row.repairs, property_row.mao]), "detail": "ARV, repairs, and MAO must be present."},
        {"name": "Buyer market coverage", "ready": bool(matching_buyers), "detail": f"Matching buyers: {len(matching_buyers)}"},
        {"name": "Verified proof of funds", "ready": bool(verified_buyers), "detail": f"Verified buyers: {len(verified_buyers)}"},
        {"name": "Deal record", "ready": existing_deal is not None, "detail": "A tenant-linked deal should exist for this property."},
        {"name": "Contract readiness", "ready": bool(existing_deal and property_row.mao), "detail": "Requires a deal and completed underwriting."},
        {"name": "Closing readiness", "ready": bool(existing_deal and verified_buyers), "detail": "Requires a deal and at least one verified buyer."},
    ]
    passed = sum(1 for item in checks if item["ready"])
    score = round((passed / len(checks)) * 100)
    status = "ready" if score == 100 else "conditional" if score >= 63 else "blocked"
    return {
        "generated_at": datetime.utcnow(),
        "status": status,
        "score": score,
        "lead": {"id": lead.id, "seller_name": lead.seller_name, "status": lead.status},
        "property": {"id": property_row.id, "address": property_row.address, "city": property_row.city, "state": property_row.state, "zip_code": property_row.zip_code, "arv": property_row.arv, "repairs": property_row.repairs, "mao": property_row.mao},
        "matching_buyers": len(matching_buyers),
        "verified_buyers": len(verified_buyers),
        "deal_id": existing_deal.id if existing_deal else None,
        "checks": checks,
        "safety": {"messages_sent": False, "calls_placed": False, "contracts_sent": False, "closing_opened": False},
    }


@router.get("/snapshot")
def snapshot(lead_id: int | None = None, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return _evaluate(db, principal, lead_id)


@router.post("/run")
def run(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    result = _evaluate(db, principal, int((payload or {}).get("lead_id") or 0) or None)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="test_deal_rehearsal",
        summary=f"Test deal rehearsal completed with score {result.get('score', 0)}",
        lead_id=(result.get("lead") or {}).get("id"),
        deal_id=result.get("deal_id"),
        metadata_json={"status": result.get("status"), "score": result.get("score"), "checks": result.get("checks"), "non_destructive": True},
    ))
    db.commit()
    return result

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .database import get_db
from .models import Buyer, Lead

router = APIRouter(prefix="/buyer-first-acquisition", tags=["buyer-first acquisition"])


def _workspace_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _price_for_match(lead: Lead) -> float | None:
    prop = lead.property
    if not prop:
        return None
    for value in (prop.mao, prop.asking_price):
        if value is not None and float(value) > 0:
            return float(value)
    return None


def _score_match(buyer: Buyer, lead: Lead) -> dict | None:
    prop = lead.property
    if not prop:
        return None

    buyer_zips = {str(item).strip() for item in (buyer.zip_codes or []) if str(item).strip()}
    property_zip = str(prop.zip_code or "").strip()
    if buyer_zips and property_zip not in buyer_zips:
        return None

    buyer_assets = {_norm(item) for item in (buyer.asset_types or []) if _norm(item)}
    property_type = _norm(prop.property_type or "single_family")
    generic_assets = {"any", "all", "residential"}
    if buyer_assets and property_type not in buyer_assets and not (buyer_assets & generic_assets):
        return None

    price = _price_for_match(lead)
    if price is not None and (price < float(buyer.min_price or 0) or price > float(buyer.max_price or 10_000_000)):
        return None

    repairs = float(prop.repairs) if prop.repairs is not None else None
    if repairs is not None and repairs > float(buyer.max_rehab or 0):
        return None

    score = 0.0
    reasons: list[str] = []

    if buyer_zips:
        score += 35
        reasons.append("exact ZIP buying-box match")
    else:
        score += 10
        reasons.append("national/unscoped buyer channel")

    if buyer_assets:
        score += 20
        reasons.append("asset type matches buyer box")
    else:
        score += 8
        reasons.append("buyer accepts broad asset types")

    if price is not None:
        score += 15
        reasons.append("acquisition price fits buyer range")
    else:
        score += 4
        reasons.append("price pending underwriting")

    if repairs is not None:
        score += 10
        reasons.append("rehab fits buyer tolerance")
    else:
        score += 3
        reasons.append("repair scope pending verification")

    if buyer.proof_of_funds_verified:
        score += 10
        reasons.append("documentary POF verified")
    else:
        reasons.append("POF pending — demand signal only")

    closing_days = max(1, int(buyer.closing_days or 14))
    if closing_days <= 10:
        score += 6
        reasons.append("fast close <=10 days")
    elif closing_days <= 14:
        score += 4
        reasons.append("fast close <=14 days")
    elif closing_days <= 30:
        score += 2

    score += min(4.0, max(0.0, float(buyer.reliability_score or 0)) / 25.0)

    lead_strength = (
        float(lead.motivation_score or 0)
        + float(lead.distress_score or 0)
        + float(lead.equity_score or 0)
    ) / 3.0
    score += min(10.0, lead_strength / 10.0)

    ready_inputs = price is not None and repairs is not None
    status = "fast_track_underwriting" if buyer.proof_of_funds_verified and score >= 80 and ready_inputs else "demand_matched"

    return {
        "score": round(min(100.0, score), 2),
        "status": status,
        "buyer_id": buyer.id,
        "buyer_name": buyer.name,
        "buyer_company": buyer.company,
        "proof_of_funds_verified": bool(buyer.proof_of_funds_verified),
        "closing_days": closing_days,
        "lead_id": lead.id,
        "property_id": prop.id,
        "address": prop.address,
        "city": prop.city,
        "state": prop.state,
        "zip_code": prop.zip_code,
        "property_type": prop.property_type,
        "match_price": price,
        "repairs": repairs,
        "arv": prop.arv,
        "mao": prop.mao,
        "reasons": reasons,
        "execution_boundary": "underwrite_verify_title_and_seller_authority_before_offer_or_outreach",
    }


def refresh_buyer_box_matches(
    db: Session,
    principal: Principal,
    limit: int = 100,
    create_tasks: bool = True,
) -> dict:
    buyer_ids = _workspace_ids(db, principal.organization_id, "buyer")
    lead_ids = _workspace_ids(db, principal.organization_id, "lead")
    if not buyer_ids or not lead_ids:
        return {
            "generated_at": datetime.now(timezone.utc),
            "buyer_count": len(buyer_ids),
            "lead_count": len(lead_ids),
            "matches": [],
            "fast_track_count": 0,
            "pof_verified_buyer_matches": 0,
            "policy": "continuous_acquisition_parallel_with_buyer_box_targeting",
        }

    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids)).order_by(
        Buyer.proof_of_funds_verified.desc(),
        Buyer.reliability_score.desc(),
        Buyer.closing_days.asc(),
    )).all()
    leads = db.scalars(select(Lead).where(
        Lead.id.in_(lead_ids),
        Lead.status != "deleted",
    ).order_by(Lead.created_at.desc())).all()

    matches: list[dict] = []
    for lead in leads:
        for buyer in buyers:
            match = _score_match(buyer, lead)
            if match:
                matches.append(match)

    matches.sort(key=lambda item: (
        bool(item["proof_of_funds_verified"]),
        item["score"],
        -int(item["closing_days"]),
    ), reverse=True)
    matches = matches[:max(1, min(500, int(limit)))]

    if create_tasks:
        top_by_lead: dict[int, dict] = {}
        for match in matches:
            current = top_by_lead.get(match["lead_id"])
            if current is None or match["score"] > current["score"]:
                top_by_lead[match["lead_id"]] = match
        for match in top_by_lead.values():
            if match["score"] < 65:
                continue
            title = f"Buyer-box fast track: lead #{match['lead_id']} → buyer #{match['buyer_id']}"
            existing = db.scalar(select(FollowUpTask).where(
                FollowUpTask.organization_id == principal.organization_id,
                FollowUpTask.lead_id == match["lead_id"],
                FollowUpTask.status == "open",
                FollowUpTask.title == title,
            ))
            if existing:
                existing.priority = max(existing.priority, min(100, int(match["score"])))
                existing.due_at = min(existing.due_at or datetime.now(timezone.utc) + timedelta(hours=4), datetime.now(timezone.utc) + timedelta(hours=4))
                continue
            db.add(FollowUpTask(
                organization_id=principal.organization_id,
                lead_id=match["lead_id"],
                assigned_user_id=principal.user_id,
                title=title,
                priority=min(100, max(70, int(match["score"]))),
                due_at=datetime.now(timezone.utc) + timedelta(hours=4),
                notes=(
                    f"Buyer demand match score {match['score']}. ZIP {match['zip_code']}; "
                    f"POF verified={match['proof_of_funds_verified']}; close={match['closing_days']} days. "
                    "Fast-track underwriting, condition, title, ownership/seller authority, and compliance. "
                    "No autonomous offer, contract, cold SMS, or cold call is authorized by this task."
                ),
            ))

        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            activity_type="buyer_box_acquisition_refresh",
            summary=f"Ranked {len(matches)} buyer-to-lead acquisition match(es)",
            metadata_json={
                "matches": len(matches),
                "fast_track": sum(1 for item in matches if item["status"] == "fast_track_underwriting"),
                "pof_verified_matches": sum(1 for item in matches if item["proof_of_funds_verified"]),
                "policy": "parallel_general_and_buyer_targeted_acquisition",
            },
        ))
        db.commit()

    return {
        "generated_at": datetime.now(timezone.utc),
        "buyer_count": len(buyers),
        "lead_count": len(leads),
        "matches": matches,
        "fast_track_count": sum(1 for item in matches if item["status"] == "fast_track_underwriting"),
        "pof_verified_buyer_matches": sum(1 for item in matches if item["proof_of_funds_verified"]),
        "policy": "continuous_general_acquisition_plus_buyer_box_fast_lane",
        "pof_policy": "documentary_verification_only_never_infer",
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return refresh_buyer_box_matches(db, principal, limit=100, create_tasks=False)


@router.post("/refresh")
def refresh(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    limit = max(1, min(500, int((payload or {}).get("limit") or 100)))
    return refresh_buyer_box_matches(db, principal, limit=limit, create_tasks=True)

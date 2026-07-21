from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, FollowUpTask, WorkspaceEntity
from .autonomy import AUTONOMY_AGENTS
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .models import AgentRun, Buyer, Deal, Lead, OpsTask, Property
from .operating_system import create_or_update_deal
from .services import calculate_mao, lead_score

router = APIRouter(prefix="/activation", tags=["operational activation"])


def _linked_ids(db: Session, organization_id: int, entity_type: str) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == entity_type,
    )).all())


def _activity(db: Session, principal: Principal, kind: str, summary: str,
              lead_id: int | None = None, deal_id: int | None = None,
              metadata: dict | None = None) -> None:
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead_id,
        deal_id=deal_id,
        activity_type=kind,
        summary=summary,
        metadata_json=metadata or {},
    ))


def _lead_payload(lead: Lead) -> dict:
    prop = lead.property
    score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
    return {
        "id": lead.id,
        "seller_name": lead.seller_name,
        "phone": lead.phone,
        "email": lead.email,
        "source": lead.source,
        "status": lead.status,
        "motivation_score": lead.motivation_score,
        "equity_score": lead.equity_score,
        "distress_score": lead.distress_score,
        "timeline_days": lead.timeline_days,
        "notes": lead.notes,
        "lead_score": score,
        "property": None if not prop else {
            "id": prop.id,
            "address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
            "property_type": prop.property_type,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
            "sqft": prop.sqft,
            "asking_price": prop.asking_price,
            "arv": prop.arv,
            "repairs": prop.repairs,
            "mao": prop.mao,
            "distress_signals": prop.distress_signals or [],
        },
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    buyer_ids = _linked_ids(db, principal.organization_id, "buyer")
    deal_ids = _linked_ids(db, principal.organization_id, "deal")
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids)).order_by(Lead.created_at.desc())).all() if lead_ids else []
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids)).order_by(Buyer.reliability_score.desc())).all() if buyer_ids else []
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids)).order_by(Deal.updated_at.desc())).all() if deal_ids else []
    return {
        "leads": [_lead_payload(item) for item in leads],
        "buyers": [{
            "id": item.id,
            "name": item.name,
            "company": item.company,
            "buyer_type": item.buyer_type,
            "phone": item.phone,
            "email": item.email,
            "zip_codes": item.zip_codes,
            "asset_types": item.asset_types,
            "min_price": item.min_price,
            "max_price": item.max_price,
            "max_rehab": item.max_rehab,
            "closing_days": item.closing_days,
            "proof_of_funds_verified": item.proof_of_funds_verified,
            "reliability_score": item.reliability_score,
        } for item in buyers],
        "deals": [{
            "id": item.id,
            "property_id": item.property_id,
            "stage": item.stage,
            "target_contract_price": item.target_contract_price,
            "target_buyer_price": item.target_buyer_price,
            "projected_assignment_fee": item.projected_assignment_fee,
            "probability_to_close": item.probability_to_close,
            "risk_score": item.risk_score,
            "next_action": item.next_action,
        } for item in deals],
    }


@router.patch("/leads/{lead_id}")
def qualify_lead(
    lead_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead or not lead.property:
        raise HTTPException(404, "Lead property not found")

    for field in ("seller_name", "phone", "email", "source", "notes"):
        if field in payload:
            setattr(lead, field, payload[field])
    for field in ("motivation_score", "equity_score", "distress_score"):
        if field in payload:
            setattr(lead, field, max(0, min(float(payload[field]), 100)))
    if "timeline_days" in payload:
        lead.timeline_days = int(payload["timeline_days"]) if payload["timeline_days"] not in (None, "") else None

    prop_payload = payload.get("property") or {}
    prop = lead.property
    for field in ("address", "city", "state", "zip_code", "property_type"):
        if field in prop_payload:
            setattr(prop, field, prop_payload[field])
    for field in ("bedrooms", "sqft"):
        if field in prop_payload:
            setattr(prop, field, int(prop_payload[field]) if prop_payload[field] not in (None, "") else None)
    for field in ("bathrooms", "asking_price", "arv", "repairs"):
        if field in prop_payload:
            setattr(prop, field, float(prop_payload[field]) if prop_payload[field] not in (None, "") else None)
    if "distress_signals" in prop_payload:
        prop.distress_signals = list(prop_payload["distress_signals"] or [])
    if prop.arv is not None and prop.repairs is not None:
        prop.mao = calculate_mao(prop.arv, prop.repairs)

    score = lead_score(lead.motivation_score, lead.equity_score, lead.distress_score)
    lead.status = "qualified" if score >= 70 else "nurture" if score >= 45 else "new"

    existing_task = db.scalar(select(OpsTask).where(
        OpsTask.lead_id == lead.id,
        OpsTask.task_type == "score_lead",
        OpsTask.status.in_(["queued", "running"]),
    ))
    if not existing_task:
        task = OpsTask(
            task_type="score_lead",
            status="queued",
            priority=int(min(100, score + (15 if lead.timeline_days is not None and lead.timeline_days <= 14 else 0))),
            lead_id=lead.id,
            payload={"organization_id": principal.organization_id, "trigger": "qualification_updated"},
        )
        db.add(task)
        db.flush()
        _workspace_link(db, principal.organization_id, "task", task.id)

    open_follow_up = db.scalar(select(FollowUpTask).where(
        FollowUpTask.organization_id == principal.organization_id,
        FollowUpTask.lead_id == lead.id,
        FollowUpTask.status == "open",
    ))
    if not open_follow_up:
        db.add(FollowUpTask(
            organization_id=principal.organization_id,
            lead_id=lead.id,
            assigned_user_id=principal.user_id,
            title=f"Contact {lead.seller_name} and verify motivation",
            priority=int(min(100, max(40, score))),
            due_at=datetime.now(timezone.utc) + timedelta(hours=4 if score >= 70 else 24),
            notes="Generated automatically after qualification update.",
        ))

    deal = None
    if score >= 70 and prop.arv is not None and prop.repairs is not None:
        deal = create_or_update_deal(db, prop.id)
        _workspace_link(db, principal.organization_id, "deal", deal.id)
        lead.status = "qualified"
        match_task = OpsTask(
            task_type="match_buyers",
            status="queued",
            priority=90,
            lead_id=lead.id,
            payload={"organization_id": principal.organization_id, "property_id": prop.id},
        )
        db.add(match_task)
        db.flush()
        _workspace_link(db, principal.organization_id, "task", match_task.id)

    _activity(db, principal, "lead_qualified", f"Qualification updated for {lead.seller_name}",
              lead_id=lead.id, deal_id=deal.id if deal else None,
              metadata={"lead_score": score, "mao": prop.mao})
    db.commit()
    db.refresh(lead)
    return {**_lead_payload(lead), "deal_id": deal.id if deal else None}


@router.post("/buyers")
def create_buyer(
    payload: dict,
    principal: Principal = Depends(require_role("disposition")),
    db: Session = Depends(get_db),
):
    name = str(payload.get("name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    if not name or not phone:
        raise HTTPException(422, "Buyer name and phone are required")
    buyer = Buyer(
        name=name,
        company=payload.get("company"),
        buyer_type=str(payload.get("buyer_type") or "cash_buyer"),
        phone=phone,
        email=payload.get("email"),
        zip_codes=[str(item).strip() for item in payload.get("zip_codes", []) if str(item).strip()],
        asset_types=payload.get("asset_types") or ["single_family"],
        min_price=float(payload.get("min_price") or 0),
        max_price=float(payload.get("max_price") or 10_000_000),
        max_rehab=float(payload.get("max_rehab") or 500_000),
        closing_days=max(1, int(payload.get("closing_days") or 14)),
        proof_of_funds_verified=bool(payload.get("proof_of_funds_verified", False)),
        reliability_score=max(0, min(float(payload.get("reliability_score") or 50), 100)),
    )
    db.add(buyer)
    db.flush()
    _workspace_link(db, principal.organization_id, "buyer", buyer.id)
    _activity(db, principal, "buyer_created", f"Buyer buy box created: {buyer.name}",
              metadata={"buyer_id": buyer.id, "zip_codes": buyer.zip_codes})
    db.commit()
    return {"id": buyer.id, "name": buyer.name, "created": True}


@router.post("/run-specialists")
def run_specialists(
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    lead_ids = _linked_ids(db, principal.organization_id, "lead")
    buyer_ids = _linked_ids(db, principal.organization_id, "buyer")
    deal_ids = _linked_ids(db, principal.organization_id, "deal")
    leads = db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all() if lead_ids else []
    buyers = db.scalars(select(Buyer).where(Buyer.id.in_(buyer_ids))).all() if buyer_ids else []
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all() if deal_ids else []
    hot = [item for item in leads if lead_score(item.motivation_score, item.equity_score, item.distress_score) >= 70]

    outputs = {
        "executive-orchestrator": {"leads": len(leads), "hot_leads": len(hot), "deals": len(deals)},
        "market-intelligence": {"markets": sorted({f"{x.property.city}, {x.property.state}" for x in leads if x.property})},
        "acquisition-source-manager": {"sources": sorted({x.source for x in leads}), "records": len(leads)},
        "seller-acquisition": {"priority_leads": [x.id for x in hot]},
        "underwriting": {"underwritten": len([x for x in leads if x.property and x.property.arv is not None and x.property.repairs is not None])},
        "buyer-intelligence": {"qualified_buyers": len(buyers), "coverage_zip_codes": sorted({z for x in buyers for z in (x.zip_codes or [])})},
        "disposition": {"deals_ready": len([x for x in deals if x.stage in {"qualified", "under_contract", "disposition"}])},
        "transaction-coordinator": {"closing_pipeline": len([x for x in deals if x.stage in {"under_contract", "closing"}])},
        "compliance": {"mode": "supervised_autonomous", "outbound_requires_approval": True},
    }

    created = []
    for definition in AUTONOMY_AGENTS:
        name = definition["name"]
        run = AgentRun(
            agent_name=name,
            objective=definition["role"],
            status="completed",
            input_json={"organization_id": principal.organization_id, "trigger": "activation_console"},
            output_json=outputs.get(name, {"status": "ready"}),
            confidence=0.9 if name in {"executive-orchestrator", "compliance"} else 0.82,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        _workspace_link(db, principal.organization_id, "agent_run", run.id)
        created.append({"id": run.id, "agent_name": name, "status": run.status})

    _activity(db, principal, "specialist_cycle", f"Ran {len(created)} specialist agents",
              metadata={"agents": [item["agent_name"] for item in created]})
    db.commit()
    return {"ran": len(created), "agents": created, "mode": "supervised_autonomous"}

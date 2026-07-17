from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .closing_command_models import ClosingIssue, ClosingMilestone, EarnestMoneyRecord, FundingRecord, TitleOrder
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .models import Deal, Lead, Property

router = APIRouter(prefix="/closing-command", tags=["title and closing command"])

DEFAULT_MILESTONES = [
    ("signed_contract", "Signed contract received"),
    ("earnest_money", "Earnest money delivered"),
    ("title_ordered", "Title ordered"),
    ("title_commitment", "Title commitment received"),
    ("title_clear", "Title cleared"),
    ("buyer_pof", "Buyer proof of funds verified"),
    ("buyer_funding", "Buyer funds confirmed"),
    ("settlement_statement", "Settlement statement approved"),
    ("closing", "Closing completed"),
    ("assignment_fee", "Assignment fee received"),
]


def _context(db: Session, principal: Principal, deal_id: int):
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    lead = db.get(Lead, prop.lead_id) if prop else None
    if not prop or not lead:
        raise HTTPException(422, "Deal requires a linked property and seller")
    if str(prop.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    return deal, prop, lead


def _dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid date: {value}") from exc


def _serialize_title(row):
    return None if not row else {
        "id": row.id, "deal_id": row.deal_id, "title_company": row.title_company,
        "contact_name": row.contact_name, "contact_email": row.contact_email, "contact_phone": row.contact_phone,
        "order_number": row.order_number, "status": row.status, "ordered_at": row.ordered_at,
        "commitment_due_at": row.commitment_due_at, "commitment_received_at": row.commitment_received_at,
        "closing_date": row.closing_date, "metadata": row.metadata_json,
    }


def _serialize_emd(row):
    return None if not row else {
        "id": row.id, "deal_id": row.deal_id, "amount": row.amount, "holder": row.holder,
        "status": row.status, "due_at": row.due_at, "received_at": row.received_at,
        "receipt_reference": row.receipt_reference, "notes": row.notes,
    }


def _serialize_funding(row):
    return None if not row else {
        "id": row.id, "deal_id": row.deal_id, "buyer_name": row.buyer_name, "source_type": row.source_type,
        "proof_of_funds_status": row.proof_of_funds_status, "proof_of_funds_reference": row.proof_of_funds_reference,
        "required_amount": row.required_amount, "verified_amount": row.verified_amount,
        "funds_due_at": row.funds_due_at, "funds_received_at": row.funds_received_at,
        "status": row.status, "notes": row.notes,
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    deal_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
    )).all())
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids)).order_by(Deal.updated_at.desc())).all() if deal_ids else []
    result = []
    for deal in deals:
        prop = db.get(Property, deal.property_id)
        title = db.scalar(select(TitleOrder).where(TitleOrder.organization_id == principal.organization_id, TitleOrder.deal_id == deal.id))
        emd = db.scalar(select(EarnestMoneyRecord).where(EarnestMoneyRecord.organization_id == principal.organization_id, EarnestMoneyRecord.deal_id == deal.id))
        funding = db.scalar(select(FundingRecord).where(FundingRecord.organization_id == principal.organization_id, FundingRecord.deal_id == deal.id))
        issues = db.scalars(select(ClosingIssue).where(ClosingIssue.organization_id == principal.organization_id, ClosingIssue.deal_id == deal.id).order_by(ClosingIssue.created_at.desc())).all()
        milestones = db.scalars(select(ClosingMilestone).where(ClosingMilestone.organization_id == principal.organization_id, ClosingMilestone.deal_id == deal.id).order_by(ClosingMilestone.sort_order)).all()
        result.append({
            "deal": {"id": deal.id, "stage": deal.stage, "strategy": deal.strategy, "target_contract_price": deal.target_contract_price, "target_buyer_price": deal.target_buyer_price, "projected_assignment_fee": deal.projected_assignment_fee, "next_action": deal.next_action},
            "property": {"address": prop.address if prop else None, "city": prop.city if prop else None, "state": prop.state if prop else None, "zip_code": prop.zip_code if prop else None},
            "title_order": _serialize_title(title), "earnest_money": _serialize_emd(emd), "funding": _serialize_funding(funding),
            "issues": [{"id": x.id, "issue_type": x.issue_type, "severity": x.severity, "status": x.status, "title": x.title, "description": x.description, "owner": x.owner, "due_at": x.due_at, "resolution": x.resolution} for x in issues],
            "milestones": [{"id": x.id, "milestone_type": x.milestone_type, "label": x.label, "status": x.status, "due_at": x.due_at, "completed_at": x.completed_at, "owner": x.owner, "notes": x.notes} for x in milestones],
        })
    return {"organization_id": principal.organization_id, "generated_at": datetime.utcnow(), "closings": result}


@router.post("/deals/{deal_id}/initialize")
def initialize(deal_id: int, payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    payload = payload or {}
    deal, prop, lead = _context(db, principal, deal_id)
    closing_date = _dt(payload.get("closing_date")) or datetime.utcnow() + timedelta(days=int(payload.get("closing_days") or 30))
    title = db.scalar(select(TitleOrder).where(TitleOrder.organization_id == principal.organization_id, TitleOrder.deal_id == deal.id))
    if not title:
        title = TitleOrder(organization_id=principal.organization_id, deal_id=deal.id, closing_date=closing_date, status="not_ordered")
        db.add(title); db.flush(); _workspace_link(db, principal.organization_id, "title_order", title.id)
    emd = db.scalar(select(EarnestMoneyRecord).where(EarnestMoneyRecord.organization_id == principal.organization_id, EarnestMoneyRecord.deal_id == deal.id))
    if not emd:
        emd = EarnestMoneyRecord(organization_id=principal.organization_id, deal_id=deal.id, amount=float(payload.get("earnest_money") or 100), due_at=datetime.utcnow() + timedelta(days=3))
        db.add(emd); db.flush(); _workspace_link(db, principal.organization_id, "earnest_money", emd.id)
    funding = db.scalar(select(FundingRecord).where(FundingRecord.organization_id == principal.organization_id, FundingRecord.deal_id == deal.id))
    if not funding:
        funding = FundingRecord(organization_id=principal.organization_id, deal_id=deal.id, required_amount=deal.target_buyer_price, funds_due_at=closing_date - timedelta(days=1))
        db.add(funding); db.flush(); _workspace_link(db, principal.organization_id, "funding_record", funding.id)
    existing = set(db.scalars(select(ClosingMilestone.milestone_type).where(ClosingMilestone.organization_id == principal.organization_id, ClosingMilestone.deal_id == deal.id)).all())
    for index, (kind, label) in enumerate(DEFAULT_MILESTONES):
        if kind not in existing:
            row = ClosingMilestone(organization_id=principal.organization_id, deal_id=deal.id, milestone_type=kind, label=label, sort_order=index, due_at=closing_date if kind == "closing" else None)
            db.add(row); db.flush(); _workspace_link(db, principal.organization_id, "closing_milestone", row.id)
    deal.stage = "closing"
    deal.next_action = "Order title, deliver earnest money, resolve title issues, verify buyer funds, and close."
    db.add(CrmActivity(organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id, deal_id=deal.id, activity_type="closing_command_initialized", summary=f"Title and closing command initialized for deal #{deal.id}", metadata_json={"closing_date": closing_date.isoformat(), "property": f"{prop.address}, {prop.city} {prop.state}"}))
    db.commit()
    return {"initialized": True, "deal_id": deal.id, "closing_date": closing_date}


@router.patch("/deals/{deal_id}/title-order")
def update_title(deal_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    deal, prop, lead = _context(db, principal, deal_id)
    row = db.scalar(select(TitleOrder).where(TitleOrder.organization_id == principal.organization_id, TitleOrder.deal_id == deal.id))
    if not row:
        row = TitleOrder(organization_id=principal.organization_id, deal_id=deal.id); db.add(row); db.flush(); _workspace_link(db, principal.organization_id, "title_order", row.id)
    for key in ["title_company", "contact_name", "contact_email", "contact_phone", "order_number", "status"]:
        if key in payload: setattr(row, key, payload.get(key))
    for key in ["ordered_at", "commitment_due_at", "commitment_received_at", "closing_date"]:
        if key in payload: setattr(row, key, _dt(payload.get(key)))
    row.metadata_json = {**(row.metadata_json or {}), **(payload.get("metadata") or {})}
    db.commit(); return _serialize_title(row)


@router.patch("/deals/{deal_id}/earnest-money")
def update_emd(deal_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    deal, prop, lead = _context(db, principal, deal_id)
    row = db.scalar(select(EarnestMoneyRecord).where(EarnestMoneyRecord.organization_id == principal.organization_id, EarnestMoneyRecord.deal_id == deal.id))
    if not row:
        row = EarnestMoneyRecord(organization_id=principal.organization_id, deal_id=deal.id); db.add(row); db.flush(); _workspace_link(db, principal.organization_id, "earnest_money", row.id)
    for key in ["amount", "holder", "status", "receipt_reference", "notes"]:
        if key in payload: setattr(row, key, payload.get(key))
    for key in ["due_at", "received_at"]:
        if key in payload: setattr(row, key, _dt(payload.get(key)))
    db.commit(); return _serialize_emd(row)


@router.patch("/deals/{deal_id}/funding")
def update_funding(deal_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    deal, prop, lead = _context(db, principal, deal_id)
    row = db.scalar(select(FundingRecord).where(FundingRecord.organization_id == principal.organization_id, FundingRecord.deal_id == deal.id))
    if not row:
        row = FundingRecord(organization_id=principal.organization_id, deal_id=deal.id); db.add(row); db.flush(); _workspace_link(db, principal.organization_id, "funding_record", row.id)
    for key in ["buyer_name", "source_type", "proof_of_funds_status", "proof_of_funds_reference", "required_amount", "verified_amount", "status", "notes"]:
        if key in payload: setattr(row, key, payload.get(key))
    for key in ["funds_due_at", "funds_received_at"]:
        if key in payload: setattr(row, key, _dt(payload.get(key)))
    db.commit(); return _serialize_funding(row)


@router.post("/deals/{deal_id}/issues")
def create_issue(deal_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    deal, prop, lead = _context(db, principal, deal_id)
    title = str(payload.get("title") or "").strip()
    if not title: raise HTTPException(422, "Issue title is required")
    row = ClosingIssue(organization_id=principal.organization_id, deal_id=deal.id, issue_type=str(payload.get("issue_type") or "other"), severity=str(payload.get("severity") or "medium"), title=title, description=payload.get("description"), owner=payload.get("owner"), due_at=_dt(payload.get("due_at")), metadata_json=payload.get("metadata") or {})
    db.add(row); db.flush(); _workspace_link(db, principal.organization_id, "closing_issue", row.id)
    db.commit(); return {"id": row.id, "status": row.status}


@router.patch("/issues/{issue_id}")
def update_issue(issue_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    row = db.get(ClosingIssue, issue_id)
    if not row or row.organization_id != principal.organization_id: raise HTTPException(404, "Closing issue not found")
    for key in ["issue_type", "severity", "status", "title", "description", "owner", "resolution"]:
        if key in payload: setattr(row, key, payload.get(key))
    if "due_at" in payload: row.due_at = _dt(payload.get("due_at"))
    if payload.get("status") == "resolved" and not row.resolved_at: row.resolved_at = datetime.utcnow()
    db.commit(); return {"id": row.id, "status": row.status}


@router.patch("/milestones/{milestone_id}")
def update_milestone(milestone_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    row = db.get(ClosingMilestone, milestone_id)
    if not row or row.organization_id != principal.organization_id: raise HTTPException(404, "Closing milestone not found")
    for key in ["status", "owner", "notes"]:
        if key in payload: setattr(row, key, payload.get(key))
    if "due_at" in payload: row.due_at = _dt(payload.get("due_at"))
    if payload.get("status") == "completed" and not row.completed_at: row.completed_at = datetime.utcnow()
    db.commit(); return {"id": row.id, "status": row.status, "completed_at": row.completed_at}

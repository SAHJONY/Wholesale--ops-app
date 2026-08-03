from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .business_os_models import BusinessObligation, BusinessPlan, BusinessTransaction, OperatingPlaybook
from .database import get_db
from .models import Deal

router = APIRouter(prefix="/business-os", tags=["business operating system"])

TRANSACTION_TYPES = {"income", "expense"}
OBLIGATION_STATUSES = {"active", "paid", "paused", "cancelled"}
CADENCES = {"one_time", "weekly", "monthly", "quarterly", "annual"}
DEFAULT_PLAYBOOKS = [
    ("Daily owner review", "management", ["Review cash and overdue obligations", "Review hot leads and deal risks", "Clear approval queue", "Assign every critical next action"]),
    ("Seller lead qualification", "acquisitions", ["Confirm property and decision maker", "Verify ownership from authoritative records", "Confirm motivation, timeline, condition, and price", "Underwrite with licensed comps", "Schedule next follow-up"]),
    ("Contract-to-close", "transaction", ["Open title", "Confirm earnest money", "Resolve title exceptions", "Verify buyer funds", "Confirm closing statement", "Record final assignment revenue"]),
    ("Weekly scorecard", "management", ["Review leads generated and contact rate", "Review appointments, offers, and contracts", "Review marketing cost per contract", "Review projected cash and runway", "Choose next week's three priorities"]),
]


def _plan(db: Session, organization_id: int) -> BusinessPlan:
    plan = db.scalar(select(BusinessPlan).where(BusinessPlan.organization_id == organization_id))
    if not plan:
        plan = BusinessPlan(organization_id=organization_id)
        db.add(plan)
        db.flush()
    return plan


def _deal_ids(db: Session, organization_id: int) -> list[int]:
    return list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "deal",
    )).all())


def _transaction(row: BusinessTransaction) -> dict:
    return {
        "id": row.id, "transaction_type": row.transaction_type, "category": row.category,
        "amount": row.amount, "occurred_on": row.occurred_on, "vendor": row.vendor,
        "description": row.description, "created_at": row.created_at,
    }


def _next_due(current: date, cadence: str) -> date:
    if cadence == "weekly":
        return current + timedelta(days=7)
    if cadence == "quarterly":
        months = 3
    elif cadence == "annual":
        months = 12
    else:
        months = 1
    month_index = current.month - 1 + months
    year = current.year + month_index // 12
    month = month_index % 12 + 1
    month_after = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    last_day = (month_after - timedelta(days=1)).day
    return date(year, month, min(current.day, last_day))


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    today = date.today()
    month_start = today.replace(day=1)
    plan = _plan(db, principal.organization_id)
    transactions = db.scalars(select(BusinessTransaction).where(
        BusinessTransaction.organization_id == principal.organization_id,
    ).order_by(BusinessTransaction.occurred_on.desc(), BusinessTransaction.id.desc()).limit(250)).all()
    month_rows = [row for row in transactions if row.occurred_on >= month_start]
    income = sum(row.amount for row in month_rows if row.transaction_type == "income")
    expenses = sum(row.amount for row in month_rows if row.transaction_type == "expense")
    marketing = sum(row.amount for row in month_rows if row.transaction_type == "expense" and row.category == "marketing")
    obligations = db.scalars(select(BusinessObligation).where(
        BusinessObligation.organization_id == principal.organization_id,
        BusinessObligation.status.in_(["active", "paid"]),
    ).order_by(BusinessObligation.next_due_on)).all()
    playbooks = db.scalars(select(OperatingPlaybook).where(
        OperatingPlaybook.organization_id == principal.organization_id,
        OperatingPlaybook.active.is_(True),
    ).order_by(OperatingPlaybook.category, OperatingPlaybook.title)).all()
    deal_ids = _deal_ids(db, principal.organization_id)
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids))).all() if deal_ids else []
    closed_this_month = [deal for deal in deals if deal.stage == "closed" and deal.updated_at.date() >= month_start]
    recorded_revenue = income
    projected_revenue = sum(deal.projected_assignment_fee or 0 for deal in deals if deal.stage not in {"closed", "dead"})
    monthly_burn = expenses or sum(item.amount for item in obligations if item.status == "active" and item.cadence == "monthly")
    cash_after_reserve = max(0, plan.cash_on_hand + income - expenses - (income * plan.tax_reserve_percent / 100))
    alerts = []
    for item in obligations:
        if item.status == "active" and item.next_due_on < today:
            alerts.append({"severity": "critical", "type": "overdue_obligation", "message": f"{item.title} was due {item.next_due_on.isoformat()}", "entity_id": item.id})
        elif item.status == "active" and item.next_due_on <= today + timedelta(days=7):
            alerts.append({"severity": "warning", "type": "upcoming_obligation", "message": f"{item.title} is due {item.next_due_on.isoformat()}", "entity_id": item.id})
    if marketing > plan.monthly_marketing_budget:
        alerts.append({"severity": "critical", "type": "marketing_budget", "message": "Marketing spend is over the monthly budget."})
    if income < plan.monthly_revenue_goal and today.day >= 20:
        alerts.append({"severity": "warning", "type": "revenue_goal", "message": "Recorded revenue is behind the monthly goal."})
    return {
        "generated_at": datetime.now(timezone.utc),
        "period": month_start.isoformat(),
        "plan": {
            "cash_on_hand": plan.cash_on_hand, "monthly_revenue_goal": plan.monthly_revenue_goal,
            "monthly_contract_goal": plan.monthly_contract_goal, "monthly_marketing_budget": plan.monthly_marketing_budget,
            "tax_reserve_percent": plan.tax_reserve_percent,
        },
        "scorecard": {
            "recorded_revenue": recorded_revenue, "expenses": expenses, "net_operating_cash": income - expenses,
            "marketing_spend": marketing, "tax_reserve": income * plan.tax_reserve_percent / 100,
            "cash_after_reserve": cash_after_reserve, "runway_months": round(cash_after_reserve / monthly_burn, 1) if monthly_burn else None,
            "contracts_closed": len(closed_this_month), "projected_pipeline_revenue": projected_revenue,
            "revenue_goal_progress": round(recorded_revenue / plan.monthly_revenue_goal * 100, 1) if plan.monthly_revenue_goal else 0,
            "contract_goal_progress": round(len(closed_this_month) / plan.monthly_contract_goal * 100, 1) if plan.monthly_contract_goal else 0,
            "marketing_budget_used": round(marketing / plan.monthly_marketing_budget * 100, 1) if plan.monthly_marketing_budget else 0,
        },
        "alerts": alerts,
        "transactions": [_transaction(row) for row in transactions[:50]],
        "obligations": [{
            "id": row.id, "title": row.title, "category": row.category, "amount": row.amount,
            "cadence": row.cadence, "next_due_on": row.next_due_on, "last_paid_on": row.last_paid_on,
            "owner": row.owner, "status": row.status,
        } for row in obligations],
        "playbooks": [{"id": row.id, "title": row.title, "category": row.category, "steps": row.steps} for row in playbooks],
    }


@router.put("/plan")
def update_plan(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    plan = _plan(db, principal.organization_id)
    for field in ("cash_on_hand", "monthly_revenue_goal", "monthly_marketing_budget"):
        if field in payload:
            setattr(plan, field, max(0, float(payload[field])))
    if "monthly_contract_goal" in payload:
        plan.monthly_contract_goal = max(1, int(payload["monthly_contract_goal"]))
    if "tax_reserve_percent" in payload:
        plan.tax_reserve_percent = max(0, min(100, float(payload["tax_reserve_percent"])))
    db.commit()
    return {"status": "updated"}


@router.post("/transactions")
def create_transaction(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    transaction_type = str(payload.get("transaction_type") or "").lower()
    if transaction_type not in TRANSACTION_TYPES:
        raise HTTPException(422, "Transaction type must be income or expense")
    amount = float(payload.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(422, "Amount must be greater than zero")
    row = BusinessTransaction(
        organization_id=principal.organization_id, transaction_type=transaction_type,
        category=str(payload.get("category") or "other").strip().lower()[:80], amount=amount,
        occurred_on=date.fromisoformat(str(payload.get("occurred_on") or date.today().isoformat())),
        vendor=str(payload.get("vendor") or "").strip()[:160] or None,
        description=str(payload.get("description") or "").strip()[:1000] or None,
        created_by_user_id=principal.user_id,
    )
    db.add(row)
    db.add(CrmActivity(organization_id=principal.organization_id, user_id=principal.user_id,
                       activity_type="business_transaction_recorded", summary=f"Recorded {transaction_type} of ${amount:,.2f}"))
    db.commit()
    db.refresh(row)
    return _transaction(row)


@router.delete("/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    row = db.scalar(select(BusinessTransaction).where(
        BusinessTransaction.id == transaction_id,
        BusinessTransaction.organization_id == principal.organization_id,
    ))
    if not row:
        raise HTTPException(404, "Transaction not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "transaction_id": transaction_id}


@router.post("/obligations")
def create_obligation(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    cadence = str(payload.get("cadence") or "monthly").lower()
    if cadence not in CADENCES:
        raise HTTPException(422, "Unsupported cadence")
    row = BusinessObligation(
        organization_id=principal.organization_id, title=str(payload.get("title") or "").strip()[:180],
        category=str(payload.get("category") or "operations").strip().lower()[:80],
        amount=max(0, float(payload.get("amount") or 0)), cadence=cadence,
        next_due_on=date.fromisoformat(str(payload.get("next_due_on") or date.today().isoformat())),
        owner=str(payload.get("owner") or "").strip()[:160] or None,
        notes=str(payload.get("notes") or "").strip()[:1000] or None,
    )
    if not row.title:
        raise HTTPException(422, "Title is required")
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.patch("/obligations/{obligation_id}")
def update_obligation(obligation_id: int, payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    row = db.scalar(select(BusinessObligation).where(
        BusinessObligation.id == obligation_id,
        BusinessObligation.organization_id == principal.organization_id,
    ))
    if not row:
        raise HTTPException(404, "Obligation not found")
    if "status" in payload:
        status = str(payload["status"]).lower()
        if status not in OBLIGATION_STATUSES:
            raise HTTPException(422, "Unsupported obligation status")
        if status == "paid":
            if row.last_paid_on == date.today():
                raise HTTPException(409, "This obligation was already recorded as paid today")
            row.last_paid_on = date.today()
            if row.amount > 0:
                db.add(BusinessTransaction(
                    organization_id=principal.organization_id, transaction_type="expense",
                    category=row.category, amount=row.amount, occurred_on=date.today(),
                    vendor=row.title, description=f"Paid {row.cadence} obligation",
                    created_by_user_id=principal.user_id,
                ))
            if row.cadence == "one_time":
                row.status = "paid"
            else:
                row.status = "active"
                row.next_due_on = _next_due(max(row.next_due_on, date.today()), row.cadence)
        else:
            row.status = status
    if "next_due_on" in payload:
        row.next_due_on = date.fromisoformat(str(payload["next_due_on"]))
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/playbooks/defaults")
def install_default_playbooks(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    created = 0
    for title, category, steps in DEFAULT_PLAYBOOKS:
        existing = db.scalar(select(OperatingPlaybook).where(
            OperatingPlaybook.organization_id == principal.organization_id,
            OperatingPlaybook.title == title,
        ))
        if not existing:
            db.add(OperatingPlaybook(organization_id=principal.organization_id, title=title, category=category, steps=steps))
            created += 1
    db.commit()
    return {"created": created, "available": len(DEFAULT_PLAYBOOKS)}

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import Principal
from app.business_os import create_obligation, create_transaction, install_default_playbooks, snapshot, update_obligation, update_plan
from app.business_os_models import BusinessTransaction
from app.database import Base
from app.main import app  # noqa: F401 - register core metadata


def principal(organization_id: int = 1) -> Principal:
    return Principal(
        organization_id=organization_id,
        organization_name=f"Business {organization_id}",
        user_id=organization_id,
        email=f"owner{organization_id}@example.com",
        name="Owner",
        role="owner",
    )


def test_business_scorecard_is_tenant_scoped_and_calculates_cash():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        update_plan({
            "cash_on_hand": 20_000,
            "monthly_revenue_goal": 50_000,
            "monthly_contract_goal": 2,
            "monthly_marketing_budget": 5_000,
            "tax_reserve_percent": 25,
        }, principal(), db)
        create_transaction({
            "transaction_type": "income", "category": "assignment_revenue",
            "amount": 10_000, "occurred_on": date.today().isoformat(),
        }, principal(), db)
        create_transaction({
            "transaction_type": "expense", "category": "marketing",
            "amount": 2_000, "occurred_on": date.today().isoformat(),
        }, principal(), db)
        db.add(BusinessTransaction(
            organization_id=2, transaction_type="income", category="assignment_revenue",
            amount=999_999, occurred_on=date.today(), created_by_user_id=2,
        ))
        db.commit()

        result = snapshot(principal(), db)
        assert result["scorecard"]["recorded_revenue"] == 10_000
        assert result["scorecard"]["expenses"] == 2_000
        assert result["scorecard"]["tax_reserve"] == 2_500
        assert result["scorecard"]["cash_after_reserve"] == 25_500
        assert result["scorecard"]["marketing_budget_used"] == 40


def test_overdue_obligation_creates_owner_alert_and_defaults_are_idempotent():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        create_obligation({
            "title": "Annual registration",
            "category": "compliance",
            "amount": 150,
            "cadence": "annual",
            "next_due_on": (date.today() - timedelta(days=1)).isoformat(),
        }, principal(), db)
        first = install_default_playbooks(principal=principal(), db=db)
        second = install_default_playbooks(principal=principal(), db=db)
        result = snapshot(principal(), db)

        assert first["created"] == 4
        assert second["created"] == 0
        assert len(result["playbooks"]) == 4
        assert result["alerts"][0]["type"] == "overdue_obligation"


def test_paying_recurring_obligation_records_expense_and_advances_due_date():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        created = create_obligation({
            "title": "CRM subscription", "category": "software", "amount": 199,
            "cadence": "monthly", "next_due_on": date.today().isoformat(),
        }, principal(), db)
        updated = update_obligation(created["id"], {"status": "paid"}, principal(), db)
        result = snapshot(principal(), db)

        assert updated["status"] == "active"
        assert result["scorecard"]["expenses"] == 199
        assert result["obligations"][0]["next_due_on"] > date.today()

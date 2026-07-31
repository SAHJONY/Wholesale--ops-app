from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class BusinessPlan(Base):
    __tablename__ = "business_plans"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_business_plan_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    cash_on_hand: Mapped[float] = mapped_column(Float, default=0)
    monthly_revenue_goal: Mapped[float] = mapped_column(Float, default=50_000)
    monthly_contract_goal: Mapped[int] = mapped_column(Integer, default=3)
    monthly_marketing_budget: Mapped[float] = mapped_column(Float, default=10_000)
    tax_reserve_percent: Mapped[float] = mapped_column(Float, default=25)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class BusinessTransaction(Base):
    __tablename__ = "business_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    transaction_type: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    amount: Mapped[float] = mapped_column(Float)
    occurred_on: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    vendor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class BusinessObligation(Base):
    __tablename__ = "business_obligations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(80), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    cadence: Mapped[str] = mapped_column(String(30), default="monthly")
    next_due_on: Mapped[date] = mapped_column(Date, index=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    last_paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class OperatingPlaybook(Base):
    __tablename__ = "operating_playbooks"
    __table_args__ = (UniqueConstraint("organization_id", "title", name="uq_playbook_org_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(80), index=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

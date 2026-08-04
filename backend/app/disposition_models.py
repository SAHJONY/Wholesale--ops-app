from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class DispositionCampaign(Base):
    __tablename__ = "disposition_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    asking_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum_assignment_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    audience_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    response_count: Mapped[int] = mapped_column(Integer, default=0)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    launched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DealBuyerMatch(Base):
    __tablename__ = "deal_buyer_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="matched", index=True)
    contacted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class BuyerOffer(Base):
    __tablename__ = "buyer_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("disposition_campaigns.id"), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float)
    earnest_money: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proof_of_funds_status: Mapped[str] = mapped_column(String(30), default="missing", index=True)
    proof_of_funds_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contingencies: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="submitted", index=True)
    ranking_score: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    selected_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AssignmentSelection(Base):
    __tablename__ = "assignment_selections"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), unique=True, index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    buyer_offer_id: Mapped[int] = mapped_column(ForeignKey("buyer_offers.id"), index=True)
    assignment_price: Mapped[float] = mapped_column(Float)
    assignment_fee: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="selected", index=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    selected_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

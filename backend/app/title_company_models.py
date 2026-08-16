from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class TitleCompanyPartner(Base):
    __tablename__ = "title_company_partners"
    __table_args__ = (
        UniqueConstraint("organization_id", "normalized_name", name="uq_title_company_partner_org_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(180))
    normalized_name: Mapped[str] = mapped_column(String(180), index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    states: Mapped[list] = mapped_column(JSON, default=list)
    counties: Mapped[list] = mapped_column(JSON, default=list)
    zip_codes: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Capability truth is intentionally separate from marketing claims.
    assignment_support: Mapped[str] = mapped_column(String(30), default="unverified", index=True)
    double_close_support: Mapped[str] = mapped_column(String(30), default="unverified", index=True)
    simultaneous_close_support: Mapped[str] = mapped_column(String(30), default="unverified")
    transactional_funding_coordination: Mapped[str] = mapped_column(String(30), default="unverified")
    remote_closing: Mapped[str] = mapped_column(String(30), default="unverified")
    e_signing: Mapped[str] = mapped_column(String(30), default="unverified")

    investor_closings_observed: Mapped[int] = mapped_column(Integer, default=0)
    wholesale_closings_observed: Mapped[int] = mapped_column(Integer, default=0)
    avg_title_turnaround_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_closing_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=50)
    fee_transparency_score: Mapped[float] = mapped_column(Float, default=50)

    underwriter: Mapped[str | None] = mapped_column(String(180), nullable=True)
    license_reference: Mapped[str | None] = mapped_column(String(220), nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class TitleCompanyDealMatch(Base):
    __tablename__ = "title_company_deal_matches"
    __table_args__ = (
        UniqueConstraint("organization_id", "deal_id", "title_company_id", name="uq_title_company_deal_match"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    title_company_id: Mapped[int] = mapped_column(ForeignKey("title_company_partners.id"), index=True)
    requested_strategy: Mapped[str] = mapped_column(String(40), default="assignment", index=True)
    score: Mapped[float] = mapped_column(Float, default=0, index=True)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    evidence_status: Mapped[str] = mapped_column(String(30), default="needs_verification", index=True)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="ranked", index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

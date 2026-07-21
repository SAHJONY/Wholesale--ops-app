from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PropertyIntelligenceScore(Base):
    __tablename__ = "property_intelligence_scores"
    __table_args__ = (
        UniqueConstraint("organization_id", "property_id", name="uq_property_intelligence_org_property"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    property_id: Mapped[int] = mapped_column(Integer, index=True)
    market_key: Mapped[str] = mapped_column(String(140), index=True)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    distress_score: Mapped[float] = mapped_column(Float, default=0)
    equity_score: Mapped[float] = mapped_column(Float, default=0)
    buyer_demand_score: Mapped[float] = mapped_column(Float, default=0)
    data_confidence: Mapped[float] = mapped_column(Float, default=0)
    ownership_verified: Mapped[bool] = mapped_column(default=False)
    projected_assignment_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list] = mapped_column(JSON, default=list)
    source_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class NationalIntelligenceRun(Base):
    __tablename__ = "national_intelligence_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    trigger: Mapped[str] = mapped_column(String(40), default="manual")
    properties_seen: Mapped[int] = mapped_column(Integer, default=0)
    properties_scored: Mapped[int] = mapped_column(Integer, default=0)
    properties_skipped: Mapped[int] = mapped_column(Integer, default=0)
    high_priority_count: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

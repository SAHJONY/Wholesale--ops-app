from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class CountyVerificationCase(Base):
    __tablename__ = "county_verification_cases"
    __table_args__ = (UniqueConstraint("organization_id", "lead_id", "status", name="uq_county_case_active"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    property_id: Mapped[int] = mapped_column(Integer, index=True)
    county: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(2), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    assigned_to_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proposed_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

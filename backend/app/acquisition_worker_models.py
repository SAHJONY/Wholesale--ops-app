from datetime import datetime, timezone

from sqlalchemy import Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class AcquisitionAutomationRun(Base):
    __tablename__ = "acquisition_automation_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "lead_id", name="uq_acquisition_automation_org_lead"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    property_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    current_step: Mapped[str] = mapped_column(String(60), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

from datetime import datetime, timezone

from sqlalchemy import Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class IntegrationReliabilityAlert(Base):
    __tablename__ = "integration_reliability_alerts"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_id", name="uq_integration_alert_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    provider_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning", index=True)
    failure_streak: Mapped[int] = mapped_column(Integer, default=0)
    affected_workflows: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    first_detected_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    last_detected_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class IntegrationReliabilityRun(Base):
    __tablename__ = "integration_reliability_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(40), default="scheduled")
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    organizations_checked: Mapped[int] = mapped_column(Integer, default=0)
    alerts_opened: Mapped[int] = mapped_column(Integer, default=0)
    alerts_resolved: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class SmsAttributionEvent(Base):
    __tablename__ = "sms_attribution_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("sms_acquisition_campaigns.id"), nullable=True, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(60), default="system")
    reference: Mapped[str | None] = mapped_column(String(180), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)

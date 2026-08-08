from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class SmsAppointmentRequest(Base):
    __tablename__ = "sms_appointment_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    conversation_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("sms_conversation_states.id"), nullable=True, index=True
    )
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="needs_confirmation", index=True)
    requested_start_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    recipient_timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    raw_preference: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class SmsFollowUpJob(Base):
    __tablename__ = "sms_follow_up_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    conversation_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("sms_conversation_states.id"), nullable=True, index=True
    )
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    due_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    recipient_timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(String(120), default="seller_follow_up")
    body_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="scheduled", index=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(180), nullable=True)
    outbound_request_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

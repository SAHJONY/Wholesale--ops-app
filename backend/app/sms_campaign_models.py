from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class SmsSmartList(Base):
    __tablename__ = "sms_smart_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class SmsMessageTemplate(Base):
    __tablename__ = "sms_message_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    pathway_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    persona_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class SmsCampaign(Base):
    __tablename__ = "sms_acquisition_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    smart_list_id: Mapped[int | None] = mapped_column(ForeignKey("sms_smart_lists.id"), nullable=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("sms_message_templates.id"), nullable=True)
    filters_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    audience_count: Mapped[int] = mapped_column(Integer, default=0)
    prepared_count: Mapped[int] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0)
    ready_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class SmsCampaignRecipient(Base):
    __tablename__ = "sms_campaign_recipients"
    __table_args__ = (UniqueConstraint("campaign_id", "lead_id", name="uq_sms_campaign_recipient_lead"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("sms_acquisition_campaigns.id"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    contact: Mapped[str] = mapped_column(String(40))
    rendered_body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="needs_compliance", index=True)
    suppression_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    outbound_request_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

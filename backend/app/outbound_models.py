from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class OutboundRequest(Base):
    __tablename__ = "outbound_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    compliance_decision_id: Mapped[int] = mapped_column(ForeignKey("compliance_decisions.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    contact: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", index=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    provider_reference: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    provider_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_response: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatched_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

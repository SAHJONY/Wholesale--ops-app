from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class SmsConversationState(Base):
    """Canonical AI working state for one seller SMS conversation.

    The transcript remains in ``sms_messages``. This row stores only the
    structured working memory the agents need to route the next turn. Keeping
    the two separate makes every extraction auditable back to the raw message
    that produced it.
    """

    __tablename__ = "sms_conversation_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)

    stage: Mapped[str] = mapped_column(String(40), default="new", index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    lead_temperature: Mapped[str] = mapped_column(String(20), default="unscored", index=True)
    opportunity_score: Mapped[int] = mapped_column(Integer, default=0)

    qualification: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    last_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    last_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

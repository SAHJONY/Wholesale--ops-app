from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class VoiceCall(Base):
    """A call this system placed or received, and what was disclosed on it.

    Two columns carry most of the weight. ``ai_disclosed`` records that the
    caller was told they were speaking with an automated system, which the FCC
    treats as material for artificial-voice calls. ``recording_consent_basis``
    records why recording was permissible, which in an all-party consent state
    is the difference between a business record and a criminal one.

    Both are stored per call rather than derived from settings later, because a
    settings change must not retroactively alter what a past call can claim.
    """

    __tablename__ = "voice_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)

    direction: Mapped[str] = mapped_column(String(10), index=True)  # outbound | inbound
    contact: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)

    provider: Mapped[str] = mapped_column(String(30), default="bland")
    provider_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    ai_disclosed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    recorded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    recording_consent_basis: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Set when the caller asked verbally not to be contacted again.
    verbal_opt_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    transcript_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

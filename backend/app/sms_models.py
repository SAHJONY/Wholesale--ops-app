from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, event, select
from sqlalchemy.orm import Mapped, mapped_column

from .auth_models import WorkspaceEntity
from .database import Base, UtcDateTime


class SmsMessage(Base):
    """Every message this system sent or received, and why sending was allowed.

    The log is not bookkeeping. Frequency limits are computed from it, opt-outs
    are proven from it, and if a send is ever challenged the row is the record
    of which gate passed and on what evidence. A message sent without a row
    here is a message nobody can account for, so the row is written before the
    provider is called.
    """

    __tablename__ = "sms_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)

    direction: Mapped[str] = mapped_column(String(10), index=True)  # outbound | inbound
    contact: Mapped[str] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(Text)

    # outbound only: which compliance decision authorised this send.
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # inbound only: the keyword recognised, if any.
    keyword: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    triggered_opt_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


def _workspace_owns_lead(connection, organization_id: int, lead_id: int) -> bool:
    return connection.execute(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    )).first() is not None


@event.listens_for(SmsMessage, "before_insert")
def _guard_sms_lead_workspace(_mapper, connection, target: SmsMessage) -> None:
    """Fail closed if a message tries to attach another tenant's global Lead ID."""
    if target.lead_id is None:
        return
    if not _workspace_owns_lead(connection, target.organization_id, target.lead_id):
        raise ValueError("SMS lead is outside this workspace")

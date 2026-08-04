from datetime import datetime, timezone

from sqlalchemy import Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UtcDateTime


class CashBuyerCandidate(Base):
    """An entity that public deed records show buying property.

    Discovered, never assumed, and never a buyer until an owner says so. A
    recorded deed proves one thing precisely -- that this grantee took title to
    this parcel on this date for this consideration -- and the rest is
    inference. The columns keep those apart: ``purchase_count`` and
    ``total_consideration`` are counted from records, while ``cash_evidence``
    reports whether anyone actually checked for a mortgage.
    """

    __tablename__ = "cash_buyer_candidates"
    __table_args__ = (
        UniqueConstraint("organization_id", "normalized_name", name="uq_cash_buyer_candidate_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)

    # As recorded, and a comparable form of it. Both are kept: the recorded
    # spelling is the evidence, the normalized one is how repeat purchases by
    # "APEX PROPERTIES LLC" and "Apex Properties, L.L.C." are recognised as one.
    grantee_name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str] = mapped_column(String(240), index=True)
    entity_type: Mapped[str] = mapped_column(String(30), default="unknown", index=True)

    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)

    purchase_count: Mapped[int] = mapped_column(Integer, default=0)
    total_consideration: Mapped[float] = mapped_column(Float, default=0)
    first_purchase_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_purchase_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)

    zip_codes: Mapped[list] = mapped_column(JSON, default=list)
    counties: Mapped[list] = mapped_column(JSON, default=list)

    # "confirmed" only when a mortgage index was searched for the same parcel
    # and date and came back clean. Absent that search the purchase may well
    # have been financed, so the honest value is "unconfirmed" -- a deed alone
    # never proves cash.
    cash_evidence: Mapped[str] = mapped_column(String(20), default="unconfirmed", index=True)
    cash_confirmed_count: Mapped[int] = mapped_column(Integer, default=0)

    # One entry per deed: instrument, parcel, date, consideration, source.
    evidence: Mapped[list] = mapped_column(JSON, default=list)

    promoted_buyer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

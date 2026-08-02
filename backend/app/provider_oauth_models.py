from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BatchDataOAuthConnection(Base):
    __tablename__ = "batchdata_oauth_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_batchdata_oauth_connection_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    client_id: Mapped[str] = mapped_column(Text)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(24), default="Bearer")
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer: Mapped[str] = mapped_column(Text)
    resource_url: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class BatchDataOAuthState(Base):
    __tablename__ = "batchdata_oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

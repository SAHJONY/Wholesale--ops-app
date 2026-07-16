from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    seller_name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    motivation_score: Mapped[float] = mapped_column(Float, default=0)
    distress_score: Mapped[float] = mapped_column(Float, default=0)
    equity_score: Mapped[float] = mapped_column(Float, default=0)
    timeline_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    property: Mapped["Property"] = relationship(back_populates="lead", cascade="all, delete-orphan", uselist=False)


class Property(Base):
    __tablename__ = "properties"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String(12), index=True)
    property_type: Mapped[str] = mapped_column(String(50), default="single_family")
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[float | None] = mapped_column(Float, nullable=True)
    sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asking_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    arv: Mapped[float | None] = mapped_column(Float, nullable=True)
    repairs: Mapped[float | None] = mapped_column(Float, nullable=True)
    mao: Mapped[float | None] = mapped_column(Float, nullable=True)
    distress_signals: Mapped[list] = mapped_column(JSON, default=list)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead: Mapped[Lead] = relationship(back_populates="property")


class Buyer(Base):
    __tablename__ = "buyers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    buyer_type: Mapped[str] = mapped_column(String(60), default="cash_buyer")
    phone: Mapped[str] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    zip_codes: Mapped[list] = mapped_column(JSON, default=list)
    asset_types: Mapped[list] = mapped_column(JSON, default=lambda: ["single_family"])
    min_price: Mapped[float] = mapped_column(Float, default=0)
    max_price: Mapped[float] = mapped_column(Float, default=10_000_000)
    max_rehab: Mapped[float] = mapped_column(Float, default=500_000)
    closing_days: Mapped[int] = mapped_column(Integer, default=14)
    proof_of_funds_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    response_rate: Mapped[float] = mapped_column(Float, default=0)
    reliability_score: Mapped[float] = mapped_column(Float, default=50)


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_call_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
    buyer_id: Mapped[int | None] = mapped_column(ForeignKey("buyers.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="created")
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

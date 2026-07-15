from pydantic import BaseModel, Field


class PropertyInput(BaseModel):
    address: str
    city: str
    state: str = Field(min_length=2, max_length=2)
    zip_code: str
    property_type: str = "single_family"
    bedrooms: int | None = None
    bathrooms: float | None = None
    sqft: int | None = None
    asking_price: float | None = None
    arv: float | None = None
    repairs: float | None = None
    distress_signals: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None


class LeadCreate(BaseModel):
    seller_name: str
    phone: str
    email: str | None = None
    source: str = "manual"
    motivation_score: float = Field(default=0, ge=0, le=100)
    equity_score: float = Field(default=0, ge=0, le=100)
    timeline_days: int | None = Field(default=None, ge=0)
    notes: str | None = None
    property: PropertyInput


class BuyerCreate(BaseModel):
    name: str
    company: str | None = None
    buyer_type: str = "cash_buyer"
    phone: str
    email: str | None = None
    zip_codes: list[str] = Field(default_factory=list)
    asset_types: list[str] = Field(default_factory=lambda: ["single_family"])
    min_price: float = Field(default=0, ge=0)
    max_price: float = Field(default=10_000_000, ge=0)
    max_rehab: float = Field(default=500_000, ge=0)
    closing_days: int = Field(default=14, ge=1)
    proof_of_funds_verified: bool = False
    response_rate: float = Field(default=0, ge=0, le=100)
    reliability_score: float = Field(default=50, ge=0, le=100)


class UnderwriteRequest(BaseModel):
    arv: float = Field(gt=0)
    repairs: float = Field(ge=0)
    assignment_fee: float = Field(default=15_000, ge=0)
    mao_factor: float = Field(default=0.70, gt=0, le=1)


class MatchResult(BaseModel):
    buyer_id: int
    buyer_name: str
    score: float
    reasons: list[str]

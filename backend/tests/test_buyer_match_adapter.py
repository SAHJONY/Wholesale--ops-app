from types import SimpleNamespace

from app.buyer_match_adapter import buyer_to_cash_profile, deal_to_matching_profile, normalize_buyer_type
from app.cash_buyer_matching import match_buyer_to_deal


def _buyer(**overrides):
    data = {
        "id": 7,
        "name": "Juan Investor",
        "company": None,
        "buyer_type": "cash_buyer",
        "zip_codes": ["77084"],
        "asset_types": ["single_family"],
        "min_price": 50000,
        "max_price": 250000,
        "max_rehab": 80000,
        "proof_of_funds_verified": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_cash_buyer_normalizes_to_individual_without_company():
    assert normalize_buyer_type(_buyer()) == "individual"


def test_cash_buyer_with_company_normalizes_to_entity():
    assert normalize_buyer_type(_buyer(company="Acme Homes LLC")) == "entity"


def test_legacy_reliability_is_not_used_as_closing_history_evidence():
    buyer = _buyer()
    buyer.reliability_score = 99
    buyer.response_rate = 1.0
    profile = buyer_to_cash_profile(buyer)
    assert profile.proof_of_funds_verified is True
    assert profile.closing_history_verified is False


def test_deal_profile_matches_verified_buyer_buying_box():
    buyer = buyer_to_cash_profile(_buyer())
    deal = SimpleNamespace(
        target_buyer_price=150000,
        target_contract_price=130000,
        projected_assignment_fee=20000,
        strategy="wholesale",
    )
    prop = SimpleNamespace(
        state="TX",
        city="Houston",
        zip_code="77084",
        property_type="single_family",
        mao=130000,
        asking_price=140000,
        arv=240000,
        repairs=45000,
        bedrooms=3,
        bathrooms=2,
        sqft=1500,
        distress_signals=["tax_delinquent"],
    )
    result = match_buyer_to_deal(buyer, deal_to_matching_profile(deal, prop))
    assert result["eligible"] is True
    assert result["score"] == 85
    assert "proof_of_funds_verified" in result["reasons"]

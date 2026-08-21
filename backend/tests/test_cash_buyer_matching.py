from app.cash_buyer_matching import BuyingBox, CashBuyer, DealForMatching, match_buyer_to_deal, rank_buyers


def _deal():
    return DealForMatching(
        state="TX", county="Harris", city="Houston", zip_code="77084",
        property_type="single_family", assignment_price=145000, arv=245000,
        equity_pct=40, rehab=45000, beds=3, baths=2, sqft=1650,
        year_built=1988, occupancy="vacant", distress_signals=("fsbo", "tax_delinquent"),
        assignment_fee=12000,
    )


def test_matches_all_supported_buyer_types_by_buying_box():
    box = BuyingBox(states=("TX",), counties=("Harris",), property_types=("single_family",), max_price=160000, min_arv=220000, max_rehab=60000)
    buyers = [CashBuyer(str(i), kind, kind, box, verified_cash_buyer=True) for i, kind in enumerate(("individual", "hedge_fund", "entity", "private_capital", "private_investor"), 1)]
    matches = rank_buyers(_deal(), buyers)
    assert {m["buyer_type"] for m in matches} == {"individual", "hedge_fund", "entity", "private_capital", "private_investor"}


def test_rejects_deal_outside_buying_box():
    buyer = CashBuyer("b1", "Buyer", "individual", BuyingBox(states=("FL",), max_price=100000))
    result = match_buyer_to_deal(buyer, _deal())
    assert result["eligible"] is False
    assert any("outside_buying_box" in reason for reason in result["reasons"])


def test_verified_capital_ranks_above_unverified_buyer():
    box = BuyingBox(states=("TX",), max_price=200000)
    verified = CashBuyer("verified", "Verified", "private_capital", box, True, True, True)
    unverified = CashBuyer("unverified", "Unverified", "individual", box)
    matches = rank_buyers(_deal(), [unverified, verified])
    assert matches[0]["buyer_id"] == "verified"
    assert matches[0]["score"] == 100
    assert matches[1]["score"] == 60


def test_contact_release_is_not_autonomous():
    buyer = CashBuyer("b1", "Buyer", "private_investor", BuyingBox(states=("TX",)))
    match = rank_buyers(_deal(), [buyer])[0]
    assert match["contact_release"] == "human_approved_only"

from app.buyer_matching_engine import buying_box_fit, classify_buyer, rank_matching_buyers


def test_classifies_major_buyer_classes():
    assert classify_buyer("Jane Smith") == "individual"
    assert classify_buyer("Apex Homes LLC") == "llc"
    assert classify_buyer("Atlas Opportunity Fund") == "fund"
    assert classify_buyer("Northstar Family Office") == "private_capital"


def test_buying_box_match_prefers_exact_local_fit():
    deal = {"property": {"zip_code": "77002", "state": "TX", "property_type": "single_family", "mao": 150000, "arv": 260000, "repairs": 45000}}
    exact = {"id": 1, "name": "Jane Smith", "zip_codes": ["77002"], "asset_types": ["single_family"], "min_price": 80000, "max_price": 220000, "max_rehab": 70000, "reliability_score": 85, "proof_of_funds_verified": True}
    broad = {"id": 2, "name": "Atlas Fund", "states": ["tx"], "asset_types": ["single_family"], "min_price": 50000, "max_price": 500000, "max_rehab": 100000, "reliability_score": 85}
    ranked = rank_matching_buyers(deal, [broad, exact])
    assert ranked[0]["buyer_id"] == 1
    assert ranked[0]["match_score"] > ranked[1]["match_score"]
    assert ranked[0]["funding_status"] == "verified"


def test_unverified_funding_is_not_promoted_to_cash():
    result = buying_box_fit(
        {"id": 3, "name": "Buyer Person", "states": ["fl"], "asset_types": ["single_family"]},
        {"property": {"state": "FL", "property_type": "single_family", "mao": 100000}},
    )
    assert result["funding_status"] == "unverified"

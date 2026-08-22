from app.real_deals import _looks_like_entity, _spread, _verification_gate


def test_verified_gate_requires_real_evidence():
    record = {
        "owner": {"type": "individual", "verified": True},
        "deed": {"instrument": "OR-2026-100"},
        "sources": [{"provider": "county clerk"}],
        "property": {"arv": 200_000, "repairs": 30_000},
        "underwriting": {
            "target_contract_price": 100_000,
            "target_buyer_price": 120_000,
            "projected_assignment_fee": 20_000,
            "minimum_assignment_fee": 10_000,
        },
        "verification": {"owner_verified": True},
    }
    assert _verification_gate(record)["cleared"] is True


def test_verified_gate_reports_every_missing_boundary():
    gate = _verification_gate({"owner": {}, "deed": {}, "sources": [], "property": {}, "underwriting": {}})
    assert gate["cleared"] is False
    assert "seller_authority_not_verified" in gate["blockers"]
    assert "title_or_deed_evidence_missing" in gate["blockers"]
    assert "source_evidence_missing" in gate["blockers"]
    assert "assignment_spread_below_minimum" in gate["blockers"]


def test_entity_owner_markers_are_rejected():
    assert _looks_like_entity("KDANDD LLC") is True
    assert _looks_like_entity("Sunshine Property Holdings Inc") is True
    assert _looks_like_entity("The Smith Family Trust") is True
    assert _looks_like_entity("First National Bank") is True


def test_individual_owner_names_pass_marker_check():
    assert _looks_like_entity("George Archibald") is False
    assert _looks_like_entity("Maria Elena Rodriguez") is False
    assert _looks_like_entity("John A Smith & Jane B Smith") is False


def test_assignment_spread_is_buyer_price_less_contract_price():
    assert _spread(60_000, 75_000) == 15_000
    assert _spread(100_000, 110_000) == 10_000
    assert _spread(100_000, 99_000) == -1_000

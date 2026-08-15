from app.real_deals import _looks_like_entity, _spread


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

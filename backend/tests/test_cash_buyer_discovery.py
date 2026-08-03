"""Cash buyer discovery from recorded deeds.

The claims here end up on a call list, so the tests target the ones that could
mislead: that a deed alone never becomes "cash", that one purchase never
becomes an active buyer, and that nothing reaches the buyer list without a
person approving it.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from app.cash_buyer_discovery import (
    MIN_CONFIDENCE_TO_PROMOTE,
    aggregate_deeds,
    classify_entity,
    normalize_name,
    score_candidate,
)


def deed(grantee, **overrides):
    row = {
        "grantee": grantee,
        "instrument": "2026-001234",
        "parcel": "12-34-567",
        "address": "100 Main St",
        "recorded_at": "2026-05-01",
        "consideration": "185000",
        "zip_code": "32501",
        "county": "Escambia",
        "source": "https://recorder.example.gov",
    }
    row.update(overrides)
    return row


def test_one_entity_spelled_differently_is_one_candidate():
    for raw in ("APEX PROPERTIES, L.L.C.", "Apex Properties LLC", "apex properties llc"):
        assert normalize_name(raw) == "apex properties"


def test_normalization_does_not_collapse_distinct_buyers():
    assert normalize_name("Apex Properties LLC") != normalize_name("Apex Holdings LLC")


def test_entity_type_is_read_from_the_recorded_name():
    assert classify_entity("Apex Properties LLC") == "llc"
    assert classify_entity("Smith Holdings Inc") == "corporation"
    assert classify_entity("Riverbend Partners LP") == "partnership"
    assert classify_entity("The Johnson Family Trust") == "trust"
    assert classify_entity("Maria Alvarez") == "individual_or_unknown"


def test_a_deed_alone_is_never_reported_as_cash():
    # The single most misleading claim this module could make.
    [candidate] = aggregate_deeds([deed("Apex Properties LLC")])
    assert candidate["cash_evidence"] == "unconfirmed"
    assert candidate["cash_confirmed_count"] == 0
    assert candidate["evidence"][0]["mortgage_index_searched"] is False


def test_cash_is_confirmed_only_by_a_search_that_found_no_mortgage():
    [candidate] = aggregate_deeds([deed("Apex Properties LLC", mortgage_found=False)])
    assert candidate["cash_evidence"] == "confirmed"
    assert candidate["evidence"][0]["mortgage_index_searched"] is True


def test_a_found_mortgage_is_not_cash():
    [candidate] = aggregate_deeds([deed("Apex Properties LLC", mortgage_found=True)])
    assert candidate["cash_evidence"] == "unconfirmed"
    assert candidate["cash_confirmed_count"] == 0
    # The search did happen; it simply found financing.
    assert candidate["evidence"][0]["mortgage_index_searched"] is True


def test_repeat_purchases_aggregate_into_one_candidate():
    candidates = aggregate_deeds([
        deed("Apex Properties LLC", parcel="1", zip_code="32501", consideration="100000"),
        deed("APEX PROPERTIES, LLC", parcel="2", zip_code="32503", consideration="150000"),
        deed("Apex Properties L.L.C.", parcel="3", zip_code="32501", consideration="120000"),
    ])
    assert len(candidates) == 1
    assert candidates[0]["purchase_count"] == 3
    assert candidates[0]["total_consideration"] == 370000
    assert sorted(candidates[0]["zip_codes"]) == ["32501", "32503"]
    assert len(candidates[0]["evidence"]) == 3


def test_first_and_last_purchase_dates_bracket_the_records():
    [candidate] = aggregate_deeds([
        deed("Apex Properties LLC", parcel="1", recorded_at="2026-01-15"),
        deed("Apex Properties LLC", parcel="2", recorded_at="2026-06-20"),
    ])
    assert candidate["first_purchase_at"].strftime("%Y-%m-%d") == "2026-01-15"
    assert candidate["last_purchase_at"].strftime("%Y-%m-%d") == "2026-06-20"


def test_a_deed_with_no_readable_grantee_is_dropped():
    # Bucketing these under a blank name would invent a prolific buyer.
    assert aggregate_deeds([deed(""), deed("   "), deed(None)]) == []


def test_one_purchase_cannot_reach_the_promotion_threshold():
    # Buying a house once is not evidence of an active cash buyer.
    assert score_candidate(1, "llc", 0) < MIN_CONFIDENCE_TO_PROMOTE


def test_repetition_is_what_earns_promotion():
    assert score_candidate(3, "llc", 0) >= MIN_CONFIDENCE_TO_PROMOTE


def test_entity_type_alone_cannot_carry_a_candidate():
    # An LLC that bought once must not outrank an individual who bought four times.
    assert score_candidate(1, "llc", 1) < score_candidate(4, "individual_or_unknown", 0)


def test_confidence_never_reaches_certainty():
    # Past purchases are not a commitment to buy again.
    assert score_candidate(50, "llc", 50) <= 95.0


def test_no_purchases_scores_nothing():
    assert score_candidate(0, "llc", 3) == 0.0


def test_candidates_are_ordered_by_strength_of_evidence():
    candidates = aggregate_deeds([
        deed("One Time Buyer LLC", parcel="9"),
        deed("Serial Investor LLC", parcel="1", mortgage_found=False),
        deed("Serial Investor LLC", parcel="2", mortgage_found=False),
        deed("Serial Investor LLC", parcel="3", mortgage_found=False),
    ])
    assert candidates[0]["grantee_name"] == "Serial Investor LLC"
    assert candidates[0]["confidence"] > candidates[1]["confidence"]


def test_malformed_consideration_does_not_break_aggregation():
    [candidate] = aggregate_deeds([
        deed("Apex Properties LLC", parcel="1", consideration="$185,000.00"),
        deed("Apex Properties LLC", parcel="2", consideration="unavailable"),
    ])
    assert candidate["purchase_count"] == 2
    assert candidate["total_consideration"] == 185000.0


def test_deed_category_writes_nothing_onto_the_distress_profile():
    from app.distress_providers import PROVIDERS_BY_ID

    spec = PROVIDERS_BY_ID["cash_purchase_deed"]
    assert spec.access == "public_record"
    assert spec.authority_tier == "county_recorder"
    # Buying a house is a sign of a buyer, not of a distressed seller.
    assert spec.category == "buyer_signal"
    assert not any("distress" in field or "delinquent" in field for field in spec.writable_fields)

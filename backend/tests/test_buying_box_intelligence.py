from datetime import datetime, timezone
from types import SimpleNamespace

from app.buying_box_intelligence import (
    buyer_match_confidence,
    observed_pattern_from_candidate,
)
from app.cash_buyer_matching import BuyingBox, CashBuyer, DealForMatching


def test_observed_pattern_keeps_recorded_history_separate():
    candidate = SimpleNamespace(
        purchase_count=3,
        cash_confirmed_count=1,
        zip_codes=["77002", "77003"],
        counties=["Harris"],
        first_purchase_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_purchase_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        evidence=[
            {"consideration": 150000, "source": "county-a"},
            {"consideration": 200000, "source": "county-a"},
            {"consideration": 250000, "source": "county-b"},
        ],
    )
    observed = observed_pattern_from_candidate(candidate)
    assert observed.purchase_count == 3
    assert observed.median_purchase_price == 200000
    assert observed.cash_confirmed_count == 1
    assert observed.source_count == 2


def test_confidence_rewards_declared_and_observed_fit_without_replacing_declared_box():
    buyer = CashBuyer(
        buyer_id="7",
        display_name="Apex Capital",
        buyer_type="private_capital",
        buying_box=BuyingBox(
            zip_codes=("77002",),
            property_types=("single_family",),
            min_price=100000,
            max_price=300000,
            max_rehab=100000,
        ),
        proof_of_funds_verified=True,
    )
    deal = DealForMatching(
        state="TX",
        county="Harris",
        city="Houston",
        zip_code="77002",
        property_type="single_family",
        assignment_price=190000,
        rehab=50000,
    )
    candidate = SimpleNamespace(
        purchase_count=4,
        cash_confirmed_count=2,
        zip_codes=["77002"],
        counties=["Harris"],
        first_purchase_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_purchase_at=datetime(2025, 10, 1, tzinfo=timezone.utc),
        evidence=[
            {"consideration": 160000, "source": "county-a"},
            {"consideration": 180000, "source": "county-a"},
            {"consideration": 210000, "source": "county-a"},
            {"consideration": 230000, "source": "county-a"},
        ],
    )
    result = buyer_match_confidence(buyer, deal, observed_pattern_from_candidate(candidate))
    assert result["eligible"] is True
    assert result["confidence"] >= 70
    assert result["components"]["declared_buying_box_fit"] > 0
    assert result["components"]["observed_purchase_fit"] > 0
    assert result["components"]["capital_evidence"] == 100


def test_declared_box_failure_remains_ineligible_even_when_history_matches():
    buyer = CashBuyer(
        buyer_id="9",
        display_name="Narrow Box Buyer",
        buyer_type="individual",
        buying_box=BuyingBox(zip_codes=("33101",), max_price=100000),
    )
    deal = DealForMatching(
        state="FL",
        zip_code="77002",
        assignment_price=190000,
    )
    candidate = SimpleNamespace(
        purchase_count=10,
        cash_confirmed_count=10,
        zip_codes=["77002"],
        counties=["Harris"],
        first_purchase_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        last_purchase_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        evidence=[{"consideration": 190000, "source": "county-a"}],
    )
    result = buyer_match_confidence(buyer, deal, observed_pattern_from_candidate(candidate))
    assert result["eligible"] is False
    assert result["components"]["declared_buying_box_fit"] == 0

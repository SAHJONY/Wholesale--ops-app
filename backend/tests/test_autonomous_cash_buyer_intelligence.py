import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.autonomous_cash_buyer_intelligence import (
    _auto_promote,
    _merge_candidate,
    _mortgage_liens_for_source,
)
from app.cash_buyer_models import CashBuyerCandidate


def principal():
    return SimpleNamespace(organization_id=1, user_id=7)


def candidate(**overrides):
    values = {
        "id": 1,
        "organization_id": 1,
        "grantee_name": "Apex Properties LLC",
        "normalized_name": "apex properties",
        "entity_type": "llc",
        "status": "pending",
        "confidence": 95.0,
        "purchase_count": 3,
        "total_consideration": 450000.0,
        "cash_evidence": "confirmed",
        "cash_confirmed_count": 2,
        "zip_codes": ["77002"],
        "counties": ["Harris"],
        "evidence": [],
        "promoted_buyer_id": None,
    }
    values.update(overrides)
    return CashBuyerCandidate(**values)


def test_no_autonomous_promotion_without_confirmed_cash_evidence():
    db = MagicMock()
    row = candidate(cash_evidence="unconfirmed", cash_confirmed_count=0)
    assert _auto_promote(db, principal(), row) is None
    db.add.assert_not_called()


def test_autonomous_promotion_never_infers_current_proof_of_funds_or_contact():
    db = MagicMock()
    row = candidate(evidence=[
        {"consideration": 125000},
        {"consideration": 190000},
        {"consideration": 155000},
    ])
    buyer = _auto_promote(db, principal(), row)
    assert buyer is not None
    assert buyer.phone == ""
    assert buyer.email is None
    assert buyer.proof_of_funds_verified is False
    assert buyer.min_price == 125000
    assert buyer.max_price == 190000
    assert buyer.zip_codes == ["77002"]
    assert row.status == "approved"


def test_deed_only_refresh_cannot_downgrade_confirmed_cash_evidence():
    db = MagicMock()
    row = candidate(cash_evidence="confirmed", cash_confirmed_count=2)
    db.scalar.return_value = row
    entry = {
        "grantee_name": "Apex Properties LLC",
        "normalized_name": "apex properties",
        "entity_type": "llc",
        "purchase_count": 4,
        "total_consideration": 600000.0,
        "cash_confirmed_count": 0,
        "cash_evidence": "unconfirmed",
        "confidence": 85.0,
        "zip_codes": ["77002", "77003"],
        "counties": ["Harris"],
        "evidence": [],
        "first_purchase_at": None,
        "last_purchase_at": None,
    }
    merged, created = _merge_candidate(db, principal(), entry)
    assert created is False
    assert merged.cash_evidence == "confirmed"
    assert merged.cash_confirmed_count == 2
    assert merged.purchase_count == 4
    assert "77003" in merged.zip_codes


def test_truncated_mortgage_index_never_proves_cash_absence():
    deed_source = SimpleNamespace(id="harris_deeds")
    mortgage_source = SimpleNamespace(id="harris_mortgages", address_field="address")

    async def fetch_rows(source, limit):
        assert source.id == "harris_mortgages"
        return [{"address": "1 Main St"}, {"address": "2 Main St"}]

    liens, status = asyncio.run(_mortgage_liens_for_source(
        deed_source,
        {"harris_mortgages": mortgage_source},
        {"harris_deeds": "harris_mortgages"},
        fetch_rows,
        2,
    ))
    assert liens is None
    assert status["cash_confirmation_available"] is False
    assert status["error"] == "mortgage_index_truncated"


def test_complete_mortgage_index_returns_normalized_lien_set():
    deed_source = SimpleNamespace(id="harris_deeds")
    mortgage_source = SimpleNamespace(id="harris_mortgages", address_field="address")

    async def fetch_rows(source, limit):
        return [{"address": "123 Main St."}, {"address": "500 Elm Ave"}]

    liens, status = asyncio.run(_mortgage_liens_for_source(
        deed_source,
        {"harris_mortgages": mortgage_source},
        {"harris_deeds": "harris_mortgages"},
        fetch_rows,
        100,
    ))
    assert liens == {"123 main st", "500 elm ave"}
    assert status["cash_confirmation_available"] is True
    assert status["mortgage_rows"] == 2

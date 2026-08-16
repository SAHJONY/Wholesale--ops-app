from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.buyer_growth_pipeline import disposition_ready_deal_ids, refresh_disposition_matches


def principal():
    return SimpleNamespace(organization_id=1, user_id=7)


def _scalar_result(values):
    result = MagicMock()
    result.all.return_value = values
    return result


def test_disposition_ready_deals_require_economics_and_nonterminal_stage():
    db = MagicMock()
    db.scalars.side_effect = [
        _scalar_result([1, 2, 3, 4]),
        _scalar_result([
            SimpleNamespace(id=1, stage="contracted", target_buyer_price=180000, target_contract_price=150000),
            SimpleNamespace(id=2, stage="underwriting", target_buyer_price=None, target_contract_price=140000),
            SimpleNamespace(id=3, stage="closed", target_buyer_price=200000, target_contract_price=160000),
            SimpleNamespace(id=4, stage="lead", target_buyer_price=None, target_contract_price=None),
        ]),
    ]
    assert disposition_ready_deal_ids(db, principal()) == [1, 2]


def test_refresh_reranks_every_disposition_ready_deal():
    db = MagicMock()
    with patch("app.buyer_growth_pipeline.disposition_ready_deal_ids", return_value=[11, 12]), patch(
        "app.buyer_growth_pipeline.rank_workspace_buyers"
    ) as rank:
        rank.side_effect = [
            {"eligible_matches": 7},
            {"eligible_matches": 4},
        ]
        result = refresh_disposition_matches(db, principal(), 25)

    assert result["disposition_ready_deals"] == 2
    assert result["deals_ranked"] == 2
    assert result["eligible_matches"] == 11
    assert result["matching_engine"] == "buying_box_intelligence_v2"
    assert rank.call_count == 2
    assert rank.call_args_list[0].args[0] == 11
    assert rank.call_args_list[0].args[1] == {"limit": 25}

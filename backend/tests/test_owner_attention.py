from datetime import datetime, timedelta, timezone

from app.auth_models import FollowUpTask
from app.executive_ops import _weighted_revenue
from app.models import Deal
from app.owner_insights import _follow_up_buckets, _iso_utc
from app.percentages import INITIAL_CLOSE_PROBABILITY, canonical_percentage


def follow_up(status: str, due_at: datetime) -> FollowUpTask:
    return FollowUpTask(
        organization_id=1,
        title="Regression follow-up",
        status=status,
        due_at=due_at,
    )


def deal(probability: float, fee: float = 15_000) -> Deal:
    return Deal(
        property_id=1,
        stage="qualified",
        projected_assignment_fee=fee,
        probability_to_close=probability,
    )


def test_attention_buckets_accept_naive_database_timestamps_without_http_500():
    now = datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc)
    items = [
        follow_up("open", datetime(2026, 8, 2, 17, 0)),
        follow_up("open", datetime(2026, 8, 2, 19, 0)),
        follow_up("open", datetime(2026, 8, 4, 18, 0)),
        follow_up("completed", datetime(2026, 8, 2, 17, 0)),
    ]

    overdue, due_soon = _follow_up_buckets(items, now)

    assert overdue == [items[0]]
    assert due_soon == [items[1]]
    assert _iso_utc(items[0].due_at) == "2026-08-02T17:00:00+00:00"


def test_attention_buckets_accept_aware_non_utc_timestamps():
    central = timezone(-timedelta(hours=5))
    now = datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc)
    item = follow_up("open", datetime(2026, 8, 2, 12, 0, tzinfo=central))

    overdue, due_soon = _follow_up_buckets([item], now)

    assert overdue == [item]
    assert due_soon == []
    assert _iso_utc(item.due_at) == "2026-08-02T17:00:00+00:00"


def test_close_probability_uses_one_canonical_zero_to_one_hundred_scale():
    assert INITIAL_CLOSE_PROBABILITY == 10
    assert canonical_percentage(0.10) == 10
    assert canonical_percentage(61) == 61
    assert canonical_percentage(150) == 100
    assert canonical_percentage(-4) == 0
    assert canonical_percentage(None) == 0


def test_weighted_revenue_supports_whole_and_legacy_fractional_probabilities():
    assert _weighted_revenue([deal(61), deal(71)]) == 19_800
    assert _weighted_revenue([deal(0.10)]) == 1_500

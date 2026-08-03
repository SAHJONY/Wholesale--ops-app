from datetime import datetime, timezone

from app.autonomy import AUTONOMY_AGENTS
from app.executive_ops import _agent_health, _as_utc
from app.models import AgentRun


def agent_run(name: str, created_at: datetime) -> AgentRun:
    return AgentRun(
        agent_name=name,
        objective="Regression test",
        status="completed",
        confidence=0.91,
        created_at=created_at,
    )


def test_naive_agent_run_timestamp_is_normalized_to_utc():
    normalized = _as_utc(datetime(2026, 8, 2, 12, 0, 0))
    assert normalized is not None
    assert normalized.tzinfo == timezone.utc
    assert normalized.isoformat() == "2026-08-02T12:00:00+00:00"


def test_agent_health_accepts_naive_database_timestamps_without_http_500():
    now = datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc)
    run = agent_run(AUTONOMY_AGENTS[0]["name"], datetime(2026, 8, 2, 17, 0, 0))

    health = _agent_health([run], now)

    current = next(item for item in health if item["name"] == run.agent_name)
    assert current["health"] == "healthy"
    assert current["last_run_at"] == "2026-08-02T17:00:00+00:00"


def test_agent_health_marks_old_naive_timestamp_stale():
    now = datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc)
    run = agent_run(AUTONOMY_AGENTS[0]["name"], datetime(2026, 8, 1, 17, 59, 0))

    health = _agent_health([run], now)

    current = next(item for item in health if item["name"] == run.agent_name)
    assert current["health"] == "stale"

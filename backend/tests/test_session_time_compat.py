from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth import HUMAN_SESSION_NAME
from app.session_time_compat import (
    _as_utc,
    _enforce_human_session_lifetime_compatible,
)


def credential(*, created_at, last_used_at=None):
    return SimpleNamespace(
        name=HUMAN_SESSION_NAME,
        created_at=created_at,
        last_used_at=last_used_at,
        revoked_at=None,
    )


def test_naive_database_timestamps_are_treated_as_utc():
    value = datetime(2026, 7, 31, 12, 0, 0)
    normalized = _as_utc(value)
    assert normalized is not None
    assert normalized.tzinfo == timezone.utc
    assert normalized.hour == 12


def test_active_session_with_naive_timestamps_does_not_crash():
    now = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)
    item = credential(
        created_at=datetime(2026, 7, 31, 17, 0),
        last_used_at=datetime(2026, 7, 31, 17, 30),
    )
    _enforce_human_session_lifetime_compatible(item, now)
    assert item.revoked_at is None


def test_expired_naive_session_returns_401_instead_of_500():
    now = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)
    item = credential(created_at=datetime(2026, 7, 30, 17, 59))
    with pytest.raises(HTTPException) as exc:
        _enforce_human_session_lifetime_compatible(item, now)
    assert exc.value.status_code == 401
    assert item.revoked_at == now


def test_idle_naive_session_returns_401_instead_of_500():
    now = datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc)
    item = credential(
        created_at=datetime(2026, 7, 31, 15, 0),
        last_used_at=datetime(2026, 7, 31, 15, 59),
    )
    with pytest.raises(HTTPException) as exc:
        _enforce_human_session_lifetime_compatible(item, now)
    assert exc.value.status_code == 401

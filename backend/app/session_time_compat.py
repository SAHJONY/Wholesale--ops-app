"""Compatibility guard for legacy timezone-naive human-session timestamps."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from . import auth


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _enforce_human_session_lifetime_compatible(credential, now: datetime) -> None:
    if credential.name != auth.HUMAN_SESSION_NAME:
        return

    now_utc = _as_utc(now)
    created_at = _as_utc(credential.created_at)
    last_seen = _as_utc(credential.last_used_at) or created_at

    if created_at and now_utc and now_utc - created_at > auth.HUMAN_SESSION_MAX_AGE:
        credential.revoked_at = now_utc
        raise HTTPException(401, "Session expired. Sign in again.")

    if last_seen and now_utc and now_utc - last_seen > auth.HUMAN_SESSION_IDLE_TIMEOUT:
        credential.revoked_at = now_utc
        raise HTTPException(401, "Session expired due to inactivity. Sign in again.")


def install_session_time_compatibility() -> None:
    """Install the compatibility guard before authenticated requests run."""
    auth._enforce_human_session_lifetime = _enforce_human_session_lifetime_compatible

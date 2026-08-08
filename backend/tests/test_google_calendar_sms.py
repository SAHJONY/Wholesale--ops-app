from datetime import datetime, timezone

from app import google_calendar_sms as calendar


def test_google_calendar_requires_all_oauth_values(monkeypatch):
    for name in ("GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert calendar.google_calendar_configured() is False
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh")
    assert calendar.google_calendar_configured() is True


def test_calendar_id_defaults_to_primary(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    assert calendar.calendar_id() == "primary"
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "acquisitions@example.com")
    assert calendar.calendar_id() == "acquisitions@example.com"


def test_event_time_is_rendered_in_seller_timezone():
    value = datetime(2026, 8, 8, 19, 0, tzinfo=timezone.utc)
    rendered = calendar._local_event_time(value, "America/New_York")
    assert rendered["timeZone"] == "America/New_York"
    assert rendered["dateTime"].startswith("2026-08-08T15:00:00")

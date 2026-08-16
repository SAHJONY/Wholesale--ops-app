import pytest

from app.authorized_acquisition import _pipeline_status
from app.autonomous_property_acquisition import (
    _normalize_scope,
    _normalize_web_record,
    _rotating_states,
    acquisition_feed_status,
)


def test_authorized_acquisition_reports_missing_feed(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PROPERTY_FEED_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = _pipeline_status()
    assert status["ready"] is False
    assert status["safety"]["review_only"] is True
    assert status["safety"]["outreach_allowed"] is False
    assert status["safety"]["autonomous_contracts"] is False
    assert any("OPENAI_API_KEY" in item for item in status["missing_configuration"])


def test_authorized_acquisition_accepts_secure_enabled_feed(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", "true")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_URL", "https://feed.example.test/properties")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_SOURCE", "county")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    status = _pipeline_status()
    assert status["ready"] is True
    assert status["feed"]["source"] == "county"
    assert status["feed"]["secure"] is True
    assert status["feed"]["provider_mode"] == "external_https"
    assert status["safety"]["owner_identity_from_feed_is_verified"] is False


def test_openai_key_self_configures_public_record_discovery(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PROPERTY_FEED_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    status = _pipeline_status()
    assert status["ready"] is True
    assert status["feed"]["enabled"] is True
    assert status["feed"]["configured"] is True
    assert status["feed"]["secure"] is True
    assert status["feed"]["source"] == "county"
    assert status["feed"]["provider_mode"] == "openai_web_public"
    assert status["feed"]["auto_configured"] is True
    assert status["feed"]["supports_manual_scope"] is True


def test_manual_scope_accepts_city_county_state_and_texas():
    assert _normalize_scope({"city": "Houston", "state": "TX"}) == {
        "city": "Houston", "county": "", "state": "TX", "state_name": "Texas"
    }
    assert _normalize_scope({"county": "Harris", "state": "Texas"}) == {
        "city": "", "county": "Harris", "state": "TX", "state_name": "Texas"
    }
    assert _normalize_scope({"state": "Florida"}) == {
        "city": "", "county": "", "state": "FL", "state_name": "Florida"
    }


def test_manual_scope_requires_state_and_disallows_city_plus_county():
    with pytest.raises(RuntimeError):
        _normalize_scope({"city": "Houston"})
    with pytest.raises(RuntimeError):
        _normalize_scope({"city": "Houston", "county": "Harris", "state": "TX"})


def test_web_candidate_requires_source_url_from_actual_search_results():
    raw = {
        "address": "10 Main St",
        "city": "Houston",
        "state": "TX",
        "zip_code": "77002",
        "distress_signals": ["tax delinquency"],
        "source_urls": ["https://publicrecords.example/10-main"],
        "source_kind": "county_tax",
        "source_claim": "Property appears on a public tax delinquency list.",
    }
    assert _normalize_web_record(raw, {"https://publicrecords.example/10-main"}, "TX") is not None
    assert _normalize_web_record(raw, {"https://different.example/source"}, "TX") is None


def test_nationwide_rotation_is_bounded_and_unique():
    markets = _rotating_states()
    assert len(markets) == 5
    assert len(set(markets)) == 5

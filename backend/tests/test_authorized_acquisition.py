from app.authorized_acquisition import _pipeline_status


def test_authorized_acquisition_reports_missing_feed(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PROPERTY_FEED_URL", raising=False)
    status = _pipeline_status()
    assert status["ready"] is False
    assert status["safety"]["review_only"] is True
    assert status["safety"]["outreach_allowed"] is False
    assert status["safety"]["autonomous_contracts"] is False


def test_authorized_acquisition_accepts_secure_enabled_feed(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", "true")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_URL", "https://feed.example.test/properties")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_SOURCE", "county")
    status = _pipeline_status()
    assert status["ready"] is True
    assert status["feed"]["source"] == "county"
    assert status["feed"]["secure"] is True
    assert status["safety"]["owner_identity_from_feed_is_verified"] is False

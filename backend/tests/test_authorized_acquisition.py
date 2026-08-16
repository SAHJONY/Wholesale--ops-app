from app.authorized_acquisition import _pipeline_status
from app.autonomous_property_acquisition import acquisition_feed_status, _attom_record, _rotating_markets


def test_authorized_acquisition_reports_missing_feed(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PROPERTY_FEED_URL", raising=False)
    monkeypatch.delenv("ATTOM_API_KEY", raising=False)
    status = _pipeline_status()
    assert status["ready"] is False
    assert status["safety"]["review_only"] is True
    assert status["safety"]["outreach_allowed"] is False
    assert status["safety"]["autonomous_contracts"] is False
    assert any("ATTOM_API_KEY" in item for item in status["missing_configuration"])


def test_authorized_acquisition_accepts_secure_enabled_feed(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", "true")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_URL", "https://feed.example.test/properties")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_SOURCE", "county")
    monkeypatch.delenv("ATTOM_API_KEY", raising=False)
    status = _pipeline_status()
    assert status["ready"] is True
    assert status["feed"]["source"] == "county"
    assert status["feed"]["secure"] is True
    assert status["feed"]["provider_mode"] == "external_https"
    assert status["safety"]["owner_identity_from_feed_is_verified"] is False


def test_attom_key_self_configures_and_auto_enables_feed(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PROPERTY_FEED_URL", raising=False)
    monkeypatch.setenv("ATTOM_API_KEY", "test-key")
    status = _pipeline_status()
    assert status["ready"] is True
    assert status["feed"]["enabled"] is True
    assert status["feed"]["configured"] is True
    assert status["feed"]["secure"] is True
    assert status["feed"]["source"] == "attom"
    assert status["feed"]["provider_mode"] == "attom_internal"
    assert status["feed"]["auto_configured"] is True


def test_attom_record_maps_only_candidate_facts():
    item = {
        "identifier": {"attomId": 123},
        "address": {"line1": "10 Main St", "locality": "Orlando", "countrySubd": "FL", "postal1": "32801"},
        "summary": {"propclass": "Single Family Residence"},
        "building": {"rooms": {"beds": 3, "bathstotal": 2}, "size": {"universalsize": 1450}},
        "location": {"latitude": "28.5", "longitude": "-81.3"},
    }
    record = _attom_record(item, "FL", "32801")
    assert record is not None
    assert record["address"] == "10 Main St"
    assert record["source"] == "attom"
    assert record["external_id"] == "123"
    assert record["provider_evidence"]["owner_verified"] is False
    assert record["provider_evidence"]["distress_verified"] is False
    assert "owner_name" not in record
    assert "arv" not in record


def test_nationwide_rotation_is_bounded_and_unique():
    markets = _rotating_markets()
    assert len(markets) == 5
    assert len(set(markets)) == 5

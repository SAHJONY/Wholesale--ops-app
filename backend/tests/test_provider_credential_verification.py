from app.providers.batchdata import _classify


def test_batchdata_verification_statuses_are_fail_closed():
    assert _classify(200) == "ready_verified"
    assert _classify(204) == "ready_verified"
    assert _classify(401) == "invalid_credentials"
    assert _classify(403) == "invalid_credentials"
    assert _classify(402) == "payment_required"
    assert _classify(429) == "rate_limited"
    assert _classify(500) == "unavailable"
    assert _classify(404) == "configured_unverified"

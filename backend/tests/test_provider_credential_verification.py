from app.provider_intelligence import _classify_verification_status


def test_batchdata_verification_statuses_are_fail_closed():
    assert _classify_verification_status(200) == "ready_verified"
    assert _classify_verification_status(204) == "ready_verified"
    assert _classify_verification_status(401) == "invalid_credentials"
    assert _classify_verification_status(403) == "invalid_credentials"
    assert _classify_verification_status(429) == "rate_limited"
    assert _classify_verification_status(500) == "unavailable"
    assert _classify_verification_status(404) == "configured_unverified"

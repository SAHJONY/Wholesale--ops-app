from app import security_middleware as security


def setup_function():
    security._ATTEMPTS.clear()
    security._BLOCKS.clear()
    security.COUNTERS["rate_limited"] = 0


def test_login_rate_limit_blocks_eleventh_attempt():
    key = "source:/human-auth/login"
    for _ in range(10):
        allowed, _ = security.check_limit(key, "/human-auth/login")
        assert allowed
    allowed, retry_after = security.check_limit(key, "/human-auth/login")
    assert not allowed
    assert retry_after == 900
    assert security.COUNTERS["rate_limited"] == 1


def test_general_route_allows_normal_request_volume():
    key = "source:/health"
    for _ in range(25):
        allowed, _ = security.check_limit(key, "/health")
        assert allowed

import os
import time

from starlette.requests import Request

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


def _request(xff: str | None = None, peer: str = "10.0.0.9"):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 0)})


def test_forwarded_for_uses_proxy_appended_hop_not_caller_supplied_one():
    """A caller that forges X-Forwarded-For must not get a fresh rate-limit
    bucket. With one proxy in front, only the rightmost hop is trustworthy."""
    os.environ["TRUSTED_PROXY_HOPS"] = "1"
    real_client = "203.0.113.7"
    spoofed = [
        _request(f"{forged}, {real_client}")
        for forged in ("1.1.1.1", "2.2.2.2", "3.3.3.3")
    ]
    fingerprints = {security._fingerprint(request) for request in spoofed}
    assert len(fingerprints) == 1, "rotating the forged hop changed the bucket"
    assert security._client_address(spoofed[0]) == real_client


def test_direct_connection_falls_back_to_peer_address():
    os.environ["TRUSTED_PROXY_HOPS"] = "1"
    assert security._client_address(_request(peer="198.51.100.4")) == "198.51.100.4"


def test_stale_buckets_are_evicted_so_tracking_stays_bounded():
    security.COUNTERS["evicted"] = 0
    now = time.time()
    for index in range(50):
        # Last activity well outside the widest policy window.
        security._ATTEMPTS[f"stale-{index}"].append(now - 4000)
    security._last_sweep = 0.0
    with security._LOCK:
        security._sweep(time.time())
    assert security.COUNTERS["evicted"] == 50
    assert len(security._ATTEMPTS) == 0


def test_blocked_keys_survive_eviction_sweep():
    now = time.time()
    security._ATTEMPTS["blocked"].append(now - 4000)
    security._BLOCKS["blocked"] = now + 900
    security._last_sweep = 0.0
    with security._LOCK:
        security._sweep(time.time())
    assert "blocked" in security._ATTEMPTS, "an active block must not be forgotten"

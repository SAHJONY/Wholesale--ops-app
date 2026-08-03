import hashlib
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_LOCK = threading.Lock()
_ATTEMPTS = defaultdict(deque)
_BLOCKS = {}
COUNTERS = {"rate_limited": 0, "evicted": 0}
AUTH_PATHS = {"/human-auth/login", "/human-auth/request-password-reset", "/human-auth/reset-password", "/human-auth/set-password"}

# Keep the tracking tables bounded. Without this every distinct client address
# leaves a permanent entry, which a caller can grow without limit.
MAX_TRACKED_KEYS = int(os.getenv("SECURITY_MAX_TRACKED_KEYS") or "20000")
_SWEEP_INTERVAL_SECONDS = 60.0
_last_sweep = 0.0


def _client_address(request: Request) -> str:
    """Resolve the caller address, ignoring the hops a client can forge.

    ``X-Forwarded-For`` is ``client, proxy1, proxy2 ...``: each proxy appends
    the peer it received the request from, so only the entries our own
    infrastructure added can be trusted. Reading the leftmost entry — which is
    whatever the caller sent — lets anyone reset their own rate-limit bucket by
    rotating one header, defeating the brute-force protection on the auth
    routes. Count back from the right by the number of proxies actually in
    front of this app instead.
    """
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    trusted_proxies = max(0, int(os.getenv("TRUSTED_PROXY_HOPS") or "1"))
    if hops and trusted_proxies:
        return hops[-trusted_proxies] if len(hops) >= trusted_proxies else hops[0]
    return request.client.host if request.client else "unknown"


def _fingerprint(request: Request) -> str:
    source = _client_address(request)
    salt = os.getenv("SECURITY_FINGERPRINT_SALT") or os.getenv("BOOTSTRAP_SECRET") or "sahjony-security"
    return hashlib.sha256(f"{salt}:{source}".encode()).hexdigest()[:24]


def _sweep(now: float) -> None:
    """Drop entries that can no longer affect a decision. Caller holds _LOCK."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL_SECONDS and len(_ATTEMPTS) < MAX_TRACKED_KEYS:
        return
    _last_sweep = now

    for key in [key for key, expiry in _BLOCKS.items() if expiry <= now]:
        del _BLOCKS[key]

    # The widest window any policy uses; older attempts cannot influence a limit.
    stale_before = now - 600
    for key in [key for key, bucket in _ATTEMPTS.items() if not bucket or bucket[-1] < stale_before]:
        if key not in _BLOCKS:
            del _ATTEMPTS[key]
            COUNTERS["evicted"] += 1

    # Still oversized after removing stale entries: shed the least recently seen.
    if len(_ATTEMPTS) > MAX_TRACKED_KEYS:
        ordered = sorted(_ATTEMPTS.items(), key=lambda item: item[1][-1] if item[1] else 0)
        for key, _ in ordered[: len(_ATTEMPTS) - MAX_TRACKED_KEYS]:
            if key not in _BLOCKS:
                del _ATTEMPTS[key]
                COUNTERS["evicted"] += 1


def _policy(path: str):
    if path == "/human-auth/login":
        return 10, 300, 900
    if path in AUTH_PATHS:
        return 12, 600, 900
    return 240, 60, 60


def check_limit(key: str, path: str):
    limit, window, block_seconds = _policy(path)
    now = time.time()
    with _LOCK:
        _sweep(now)
        blocked_until = _BLOCKS.get(key, 0)
        if blocked_until > now:
            return False, max(1, int(blocked_until - now))
        bucket = _ATTEMPTS[key]
        while bucket and bucket[0] < now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            _BLOCKS[key] = now + block_seconds
            COUNTERS["rate_limited"] += 1
            return False, block_seconds
        bucket.append(now)
        return True, 0


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = f"{_fingerprint(request)}:{request.url.path}"
        allowed, retry_after = check_limit(key, request.url.path)
        if allowed:
            response = await call_next(request)
        else:
            response = JSONResponse({"detail": "Too many requests. Try again later."}, status_code=429)
            response.headers["Retry-After"] = str(retry_after)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if os.getenv("VERCEL_ENV") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def runtime_snapshot():
    now = time.time()
    with _LOCK:
        return {
            "active_blocks": sum(1 for expiry in _BLOCKS.values() if expiry > now),
            "tracked_buckets": len(_ATTEMPTS),
            "max_tracked_keys": MAX_TRACKED_KEYS,
            **COUNTERS,
        }

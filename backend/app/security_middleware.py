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
COUNTERS = {"rate_limited": 0}
AUTH_PATHS = {"/human-auth/login", "/human-auth/request-password-reset", "/human-auth/reset-password", "/human-auth/set-password"}


def _fingerprint(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    source = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    salt = os.getenv("SECURITY_FINGERPRINT_SALT") or os.getenv("BOOTSTRAP_SECRET") or "sahjony-security"
    return hashlib.sha256(f"{salt}:{source}".encode()).hexdigest()[:24]


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
        return {"active_blocks": sum(1 for expiry in _BLOCKS.values() if expiry > now), "tracked_buckets": len(_ATTEMPTS), **COUNTERS}

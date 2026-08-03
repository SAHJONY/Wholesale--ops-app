#!/usr/bin/env python3
"""Validate that production authentication uses the same-origin gateway.

Usage:
    python scripts/auth_gateway_check.py
    python scripts/auth_gateway_check.py --base-url https://example.vercel.app
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIN_PAGE = ROOT / "frontend/app/login/page.tsx"
MIDDLEWARE = ROOT / "frontend/middleware.ts"
PROXY_ROUTE = ROOT / "frontend/app/api/owner-access/[action]/route.ts"


def static_checks() -> list[str]:
    errors: list[str] = []
    required_files = [LOGIN_PAGE, MIDDLEWARE, PROXY_ROUTE]
    for path in required_files:
        if not path.exists():
            errors.append(f"Missing required auth gateway file: {path.relative_to(ROOT)}")

    if errors:
        return errors

    login = LOGIN_PAGE.read_text()
    middleware = MIDDLEWARE.read_text()
    proxy = PROXY_ROUTE.read_text()

    if "fetch('/api/owner-access/login'" not in login:
        errors.append("Unified login does not use the same-origin login gateway.")
    if "fetch('/api/owner-access/health'" not in login:
        errors.append("Unified login does not use the same-origin health gateway.")
    if "https://backend-" in login:
        errors.append("Unified login contains a direct production backend URL.")
    if "pathname === '/owner'" not in middleware or "pathname === '/owner-access'" not in middleware:
        errors.append("Legacy owner entry points are not both routed to /login.")
    if "'/human-auth/login'" not in proxy or "'/health'" not in proxy:
        errors.append("Owner-access proxy does not map both health and login endpoints.")

    return errors


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"raw": raw}
        return exc.code, data


def live_checks(base_url: str) -> list[str]:
    errors: list[str] = []
    base = base_url.rstrip("/")
    status, health = request_json(f"{base}/api/owner-access/health")
    if status != 200 or health.get("status") != "ok":
        errors.append(f"Health gateway failed: HTTP {status} {health}")

    status, login = request_json(
        f"{base}/api/owner-access/login",
        method="POST",
        payload={"email": "auth-smoke@example.invalid", "password": "invalid"},
    )
    if status not in {400, 401, 403, 429}:
        errors.append(f"Login gateway returned unexpected HTTP {status}: {login}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="Optional deployed frontend URL for live gateway checks")
    args = parser.parse_args()

    errors = static_checks()
    if args.base_url:
        errors.extend(live_checks(args.base_url))

    if errors:
        print("AUTH GATEWAY CHECK: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("AUTH GATEWAY CHECK: PASS")
    print("- Unified login uses same-origin health and login gateways")
    print("- Legacy owner sign-in entry points route to /login")
    if args.base_url:
        print("- Live health and invalid-credential login behavior verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())

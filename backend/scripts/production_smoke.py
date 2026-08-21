from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.getenv(
    "SMOKE_BASE_URL",
    "https://wholesale-ops-app-juan-gonzalezs-projects-94b6dfe9.vercel.app/api/backend",
).rstrip("/")
TOKEN = os.getenv("SMOKE_OWNER_TOKEN", "").strip()
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "20"))

PUBLIC_CHECKS = ["/health", "/openapi.json"]
AUTH_CHECKS = [
    "/deployment/status",
    "/workspace/dashboard",
    "/jobs/snapshot",
    "/go-live/snapshot",
    "/launch-validation/snapshot",
    "/national-intelligence/snapshot",
    "/real-estate-intelligence/snapshot",
    "/deal-execution/snapshot",
    "/closing-command/snapshot",
]


def request(path: str, authenticated: bool) -> tuple[int, str]:
    headers = {"Accept": "application/json", "User-Agent": "sahjony-production-smoke/1.0"}
    if authenticated:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(f"{BASE_URL}{path}", headers=headers)
    try:
        with urlopen(req, timeout=TIMEOUT) as response:
            return response.status, response.read(5000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read(5000).decode("utf-8", errors="replace")
    except URLError as exc:
        return 0, f"{type(exc.reason).__name__}: {exc.reason}"


def main() -> int:
    results: list[dict] = []
    failed = False

    for path in PUBLIC_CHECKS:
        status, body = request(path, authenticated=False)
        ok = 200 <= status < 300
        failed = failed or not ok
        results.append({"path": path, "authenticated": False, "status": status, "ok": ok, "detail": body[:300]})

    if not TOKEN:
        results.append({
            "path": "authenticated checks",
            "authenticated": True,
            "status": 0,
            "ok": False,
            "detail": "SMOKE_OWNER_TOKEN is not configured",
        })
        failed = True
    else:
        for path in AUTH_CHECKS:
            status, body = request(path, authenticated=True)
            ok = 200 <= status < 300
            failed = failed or not ok
            results.append({"path": path, "authenticated": True, "status": status, "ok": ok, "detail": body[:300]})

    print(json.dumps({"base_url": BASE_URL, "passed": not failed, "checks": results}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

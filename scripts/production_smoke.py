#!/usr/bin/env python3
"""Read-only production smoke checks for the deployed frontend and API."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OWNER_ROUTES = (
    "/owner", "/owner/acquisition", "/owner/acquisition-automation", "/owner/activate",
    "/owner/attention", "/owner/audit", "/owner/buyer-intake", "/owner/closing",
    "/owner/communications", "/owner/continuity", "/owner/county", "/owner/data-intake",
    "/owner/deals", "/owner/disposition", "/owner/events", "/owner/go-live",
    "/owner/integrations", "/owner/intelligence", "/owner/jobs", "/owner/launch-validation",
    "/owner/national-intelligence", "/owner/operations", "/owner/provider-activation",
    "/owner/public-data", "/owner/real-estate-intelligence", "/owner/security", "/owner/sessions",
    "/owner/system-health", "/owner/test-deal",
)


def fetch(url: str) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": "sahjony-production-smoke/1.0"})
    with urlopen(request, timeout=15) as response:
        return response.status, response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--api-url", required=True)
    args = parser.parse_args()
    failures: list[str] = []

    checks = [("api health", f"{args.api_url.rstrip('/')}/health")]
    checks.extend((f"owner page {route}", f"{args.frontend_url.rstrip('/')}{route}") for route in OWNER_ROUTES)
    for label, url in checks:
        try:
            status, _ = fetch(url)
            if status != 200:
                failures.append(f"{label}: HTTP {status}")
        except (HTTPError, URLError, TimeoutError) as exc:
            failures.append(f"{label}: {exc}")

    try:
        status, body = fetch(f"{args.api_url.rstrip('/')}/openapi.json")
        schema = json.loads(body)
        operations = sum(len({method for method in methods if method.lower() in {"get", "post", "put", "patch", "delete"}}) for methods in schema["paths"].values())
        if status != 200 or operations < 1:
            failures.append("OpenAPI contains no API operations")
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        failures.append(f"OpenAPI: {exc}")
        operations = 0

    print(json.dumps({"ok": not failures, "owner_pages": len(OWNER_ROUTES), "api_operations": operations, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

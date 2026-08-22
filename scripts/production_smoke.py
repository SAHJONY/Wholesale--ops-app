#!/usr/bin/env python3
"""Read-only production smoke checks for the deployed frontend and API."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

OWNER_ROUTES = (
    "/owner", "/owner/acquisition", "/owner/acquisition-automation", "/owner/activate",
    "/owner/attention", "/owner/audit", "/owner/buyer-intake", "/owner/closing",
    "/owner/communications", "/owner/continuity", "/owner/county", "/owner/data-intake",
    "/owner/deals", "/owner/disposition", "/owner/events", "/owner/go-live",
    "/owner/integrations", "/owner/intelligence", "/owner/jobs", "/owner/launch-validation",
    "/owner/national-intelligence", "/owner/nationwide-data", "/owner/operations", "/owner/provider-activation",
    "/owner/public-data", "/owner/real-estate-intelligence", "/owner/security", "/owner/sessions",
    "/owner/system-health", "/owner/test-deal",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url: str, *, follow_redirects: bool = True) -> tuple[int, bytes, dict[str, str]]:
    request = Request(url, headers={"User-Agent": "sahjony-production-smoke/1.0"})
    opener = build_opener() if follow_redirects else build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        if not follow_redirects and exc.code in {301, 302, 303, 307, 308}:
            return exc.code, exc.read(), dict(exc.headers.items())
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--api-url", required=True)
    args = parser.parse_args()
    failures: list[str] = []

    try:
        status, _, _ = fetch(f"{args.api_url.rstrip('/')}/health")
        if status != 200:
            failures.append(f"api health: HTTP {status}")
    except (HTTPError, URLError, TimeoutError) as exc:
        failures.append(f"api health: {exc}")

    protected_routes = 0
    for route in OWNER_ROUTES:
        try:
            status, _, headers = fetch(f"{args.frontend_url.rstrip('/')}{route}", follow_redirects=False)
            location = headers.get("Location", "")
            if status != 307 or not location.startswith("/login?returnTo="):
                failures.append(f"owner protection {route}: HTTP {status}, location={location!r}")
            else:
                protected_routes += 1
        except (HTTPError, URLError, TimeoutError) as exc:
            failures.append(f"owner protection {route}: {exc}")

    try:
        status, body, _ = fetch(f"{args.api_url.rstrip('/')}/openapi.json")
        schema = json.loads(body)
        operations = sum(len({method for method in methods if method.lower() in {"get", "post", "put", "patch", "delete"}}) for methods in schema["paths"].values())
        if status != 200 or operations < 1:
            failures.append("OpenAPI contains no API operations")
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        failures.append(f"OpenAPI: {exc}")
        operations = 0

    print(json.dumps({"ok": not failures, "owner_routes_protected": protected_routes, "api_operations": operations, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

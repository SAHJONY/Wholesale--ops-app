#!/usr/bin/env python3
"""Answer one question: can this deployment produce a verified lead right now?

A lead is only actionable here when its address resolves to a real, locatable
place, and distress leads additionally need a county feed. Those depend on
outbound HTTPS to hosts that a restrictive network policy will silently refuse.
When that happens the console reports zero verified leads and gives no reason,
because from the application's point of view the geocoder simply returned
nothing.

scripts/verify_market_data.py already proves the market-data sources (Census
ACS, FHFA, FEMA). It does not touch the geocoder or either distress transport,
which is precisely the path the verified-lead rule depends on. This covers that
gap and reports each host as reachable, blocked, or erroring, so a failure names
the host to allowlist instead of surfacing as an empty dashboard.

    python scripts/preflight_data_access.py            # check every host
    python scripts/preflight_data_access.py --json     # machine-readable

No host here requires an API key or a paid contract.

Exit codes: 0 the verified-lead path works, 1 it is degraded, 2 it is blocked.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

TIMEOUT_SECONDS = 20

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

# Each probe is a real request that returns a small payload. `critical` marks a
# host the verified-lead rule cannot work without; the rest widen coverage but
# do not, on their own, stop a lead from being verified.
PROBES: list[dict[str, Any]] = [
    {
        "id": "census_geocoder",
        "host": "geocoding.geo.census.gov",
        "critical": True,
        "purpose": "Resolves an address to a real, locatable place. Without it no lead verifies.",
        "url": "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + urlencode({
            "address": "1600 Pennsylvania Ave NW, Washington, DC 20500",
            "benchmark": "Public_AR_Current",
            "format": "json",
        }),
        "expect": lambda body: bool(
            (body.get("result") or {}).get("addressMatches")
        ),
        "expect_detail": "a match for a known-good address",
    },
    {
        "id": "census_acs",
        "host": "api.census.gov",
        "critical": False,
        "purpose": "County demographic and housing context used in market scoring.",
        "url": "https://api.census.gov/data/2023/acs/acs5?" + urlencode({
            "get": "NAME,B01003_001E",
            "for": "county:033",
            "in": "state:12",
        }),
        "expect": lambda body: isinstance(body, list) and len(body) > 1,
        "expect_detail": "a header row and at least one data row",
    },
    {
        "id": "socrata",
        "host": "api.us.socrata.com",
        "critical": False,
        "purpose": "Discovers county open-data portals carrying distress records.",
        "url": "https://api.us.socrata.com/api/catalog/v1?" + urlencode({
            "q": "code violations",
            "limit": "1",
        }),
        "expect": lambda body: "results" in body,
        "expect_detail": "a catalog result set",
    },
    {
        "id": "arcgis",
        "host": "www.arcgis.com",
        "critical": False,
        "purpose": "The other county distress transport, for FeatureServer datasets.",
        "url": "https://www.arcgis.com/sharing/rest/search?" + urlencode({
            "q": "tax delinquent",
            "f": "json",
            "num": "1",
        }),
        "expect": lambda body: "results" in body,
        "expect_detail": "a portal search result set",
    },
]


def probe(entry: dict[str, Any]) -> dict[str, Any]:
    """Make one real request and classify the outcome.

    The distinction that matters is between a host that refused the connection
    and a host that answered with something unexpected: the first is a network
    policy to change, the second is a contract that drifted.
    """
    request = urllib.request.Request(
        entry["url"],
        headers={"User-Agent": "sahjony-wholesale-os/preflight", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        # An HTTP status means we reached something. A proxy denial usually
        # arrives as 403/407 with a non-JSON body, so keep a little of it.
        body = " ".join((exc.read() or b"")[:200].decode("utf-8", "replace").split())
        blocked = exc.code in (403, 407) and not body.lstrip().startswith(("{", "["))
        return {
            "state": "blocked" if blocked else "error",
            "status": exc.code,
            "detail": f"HTTP {exc.code}" + (f": {body}" if body else ""),
        }
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"state": "blocked", "status": None, "detail": f"{type(exc).__name__}: {reason}"}
    except Exception as exc:  # noqa: BLE001 - a preflight must not itself crash
        return {"state": "error", "status": None, "detail": f"{type(exc).__name__}: {exc}"}

    try:
        body = json.loads(raw)
    except ValueError:
        # Collapsed to one line: an HTML error page would otherwise wrap the
        # report across a dozen rows and bury the hosts that need allowlisting.
        preview = " ".join(raw[:200].decode("utf-8", "replace").split())
        return {
            "state": "error",
            "status": status,
            "detail": f"HTTP {status} but the body was not JSON: {preview}",
        }

    if not entry["expect"](body):
        return {
            "state": "error",
            "status": status,
            "detail": f"HTTP {status} but the payload did not contain {entry['expect_detail']}",
        }
    return {"state": "reachable", "status": status, "detail": f"HTTP {status}, returned {entry['expect_detail']}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check outbound access for the verified-lead path")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output only")
    args = parser.parse_args()

    results = []
    for entry in PROBES:
        outcome = probe(entry)
        results.append({
            "id": entry["id"],
            "host": entry["host"],
            "critical": entry["critical"],
            "purpose": entry["purpose"],
            **outcome,
        })

    critical_blocked = [r for r in results if r["critical"] and r["state"] != "reachable"]
    optional_blocked = [r for r in results if not r["critical"] and r["state"] != "reachable"]
    exit_code = 2 if critical_blocked else (1 if optional_blocked else 0)

    if args.json:
        print(json.dumps({
            "verified_lead_path": "blocked" if critical_blocked else ("degraded" if optional_blocked else "ready"),
            "hosts_to_allowlist": [r["host"] for r in results if r["state"] == "blocked"],
            "results": results,
        }, indent=2))
        return exit_code

    print("Preflight: outbound access required to verify a lead")
    print(f"{DIM}  No host below needs an API key or a paid contract.{RESET}\n")
    for row in results:
        label = f"{row['host']}{DIM} ({'required' if row['critical'] else 'optional'}){RESET}"
        if row["state"] == "reachable":
            print(f"{GREEN}  PASS{RESET} {label}")
        elif row["state"] == "blocked":
            print(f"{RED}  BLOCKED{RESET} {label}")
        else:
            print(f"{YELLOW}  ERROR{RESET} {label}")
        print(f"{DIM}         {row['purpose']}{RESET}")
        print(f"{DIM}         {row['detail']}{RESET}")

    print("\n" + "=" * 70)
    if exit_code == 0:
        print(f"{GREEN}The verified-lead path can reach everything it needs.{RESET}")
        return 0

    to_allow = sorted({r["host"] for r in results if r["state"] == "blocked"})
    if critical_blocked:
        print(f"{RED}The verified-lead path is blocked.{RESET} No lead can be verified, so the")
        print("console will show zero verified leads no matter how many properties are loaded.")
    else:
        print(f"{YELLOW}Leads can be verified, but distress and market context are degraded.{RESET}")

    if to_allow:
        print("\nAllow outbound HTTPS to:")
        for host in to_allow:
            print(f"  - {host}")
    errored = [r for r in results if r["state"] == "error"]
    if errored:
        print("\nReached but answered unexpectedly (a changed contract, not a firewall):")
        for row in errored:
            print(f"  - {row['host']}: {row['detail']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

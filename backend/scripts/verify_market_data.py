#!/usr/bin/env python3
"""Prove the free public data connectors work against live endpoints.

Needs outbound HTTPS to api.census.gov, geocoding.geo.census.gov, www.fhfa.gov,
hazards.fema.gov, and www.fema.gov. It makes real requests, prints what came
back, and exits non-zero if a source is unreachable or its schema has drifted.

    python scripts/verify_market_data.py                    # default sample markets
    python scripts/verify_market_data.py 32501 30310        # specific ZIPs
    python scripts/verify_market_data.py --state FL         # state index check
    python scripts/verify_market_data.py --address "1 Main St, Tampa, FL"
    python scripts/verify_market_data.py --skip-fema        # market data only
    python scripts/verify_market_data.py --no-cache         # force live fetches

No source requires an API key. Setting CENSUS_API_KEY (free) only raises the
daily quota.

Exit codes: 0 all live, 1 partially degraded, 2 nothing reachable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import flood_risk, market_data  # noqa: E402

# Deliberately spread across price tiers and regions so a passing run says
# something about coverage rather than one lucky ZIP.
DEFAULT_ZIPS = ["32501", "30310", "44105", "35211", "65807"]

# Coastal and inland addresses, so a passing run exercises both an SFHA and a
# minimal-risk determination rather than one lucky lookup.
DEFAULT_ADDRESSES = [
    "1 S Palafox Pl, Pensacola, FL 32502",
    "100 Peachtree St NW, Atlanta, GA 30303",
]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def ok(message: str) -> None:
    print(f"{GREEN}  PASS{RESET} {message}")


def fail(message: str) -> None:
    print(f"{RED}  FAIL{RESET} {message}")


def warn(message: str) -> None:
    print(f"{YELLOW}  WARN{RESET} {message}")


def money(value: float | None) -> str:
    return f"${value:,.0f}" if value else "not published"


def verify_census(zip_codes: list[str], use_cache: bool) -> bool:
    print(f"\n{DIM}--- U.S. Census Bureau ACS 5-Year (api.census.gov, no key required) ---{RESET}")
    passed = 0
    for zip_code in zip_codes:
        try:
            context = market_data.fetch_market_context(zip_code, use_cache=use_cache)
        except market_data.MarketDataSchemaError as exc:
            fail(f"{zip_code}: schema drift — {exc}")
            continue
        except market_data.MarketDataUnavailable as exc:
            warn(f"{zip_code}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            fail(f"{zip_code}: {type(exc).__name__}: {exc}")
            continue

        moe = context.median_home_value_moe
        moe_text = f" ±{money(moe)}" if moe else ""
        detail = (
            f"median value {money(context.median_home_value)}{moe_text}"
            f" · rent {money(context.median_gross_rent)}"
            f" · owner-occupied {context.owner_occupancy_rate:.0%}"
            if context.owner_occupancy_rate is not None
            else f"median value {money(context.median_home_value)}{moe_text}"
        )
        vacancy = f" · vacancy {context.vacancy_rate:.1%}" if context.vacancy_rate is not None else ""
        built = f" · median built {context.median_year_built}" if context.median_year_built else ""
        ok(f"{zip_code}: {detail}{vacancy}{built}{' (cached)' if context.cached else ''}")
        for caveat in context.caveats:
            print(f"{DIM}         {caveat}{RESET}")
        passed += 1

    print(f"  {passed}/{len(zip_codes)} ZIP codes returned Census data")
    return passed > 0


def verify_fhfa(zip_codes: list[str], state: str | None, use_cache: bool) -> bool:
    print(f"\n{DIM}--- FHFA House Price Index (www.fhfa.gov, no key required) ---{RESET}")
    print(f"{DIM}  Note: the ZIP5 file is large; the first fetch may take a while.{RESET}")
    measured = 0

    for zip_code in zip_codes:
        try:
            rate = market_data.fetch_appreciation(
                zip_code=zip_code, use_cache=use_cache, allow_fallback=False
            )
        except market_data.MarketDataSchemaError as exc:
            fail(f"{zip_code}: schema drift — {exc}")
            print(
                f"{DIM}         FHFA reorganised its site in 2024. Set FHFA_HPI_ZIP5_URL "
                f"to the current dataset URL.{RESET}"
            )
            continue
        except market_data.MarketDataUnavailable as exc:
            warn(f"{zip_code}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            fail(f"{zip_code}: {type(exc).__name__}: {exc}")
            continue

        ok(
            f"{zip_code}: {rate.annual_rate:+.2%}/yr ({rate.monthly_rate:+.4%}/mo) "
            f"at {rate.level} level, period {rate.period}"
        )
        measured += 1

    if state:
        try:
            rate = market_data.fetch_appreciation(
                state=state, use_cache=use_cache, allow_fallback=False
            )
            ok(f"{state}: {rate.annual_rate:+.2%}/yr statewide, period {rate.period}")
            measured += 1
        except Exception as exc:  # noqa: BLE001
            fail(f"{state}: {type(exc).__name__}: {exc}")

    if measured:
        print(f"  {measured} measured appreciation rate(s) retrieved")
    else:
        fail("No measured appreciation rate could be retrieved from any level.")
        print(
            f"{DIM}         Underwriting will fall back to the built-in constant and label "
            f"it measured=false.{RESET}"
        )
    return measured > 0


def verify_plausibility(zip_code: str, use_cache: bool) -> None:
    print(f"\n{DIM}--- ARV plausibility screen ---{RESET}")
    try:
        context = market_data.fetch_market_context(zip_code, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        warn(f"Skipped: could not load Census context for {zip_code} ({exc})")
        return
    if not context.median_home_value:
        warn(f"Skipped: Census published no median home value for {zip_code}")
        return

    median = context.median_home_value
    for label, arv in (
        ("realistic renovated", median * 1.25),
        ("suspiciously high", median * 4.0),
        ("suspiciously low", median * 0.2),
    ):
        result = market_data.check_arv_plausibility(arv, context)
        print(f"  {label:<22} {money(arv):>12} -> {result['verdict']}")


def verify_fema(addresses: list[str], zip_code: str, use_cache: bool) -> bool:
    print(f"\n{DIM}--- FEMA flood data (hazards.fema.gov + fema.gov, no key required) ---{RESET}")
    resolved = 0

    for address in addresses:
        try:
            geocode = flood_risk.geocode_address(address)
        except Exception as exc:  # noqa: BLE001
            fail(f"geocode {address!r}: {type(exc).__name__}: {exc}")
            continue
        ok(f"geocoded {address!r} -> {geocode.latitude:.5f}, {geocode.longitude:.5f}")

        try:
            zone = flood_risk.lookup_flood_zone(
                geocode.latitude, geocode.longitude, use_cache=use_cache
            )
        except market_data.MarketDataSchemaError as exc:
            fail(f"NFHL schema drift — {exc}")
            continue
        except market_data.MarketDataUnavailable as exc:
            warn(f"NFHL: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            fail(f"NFHL: {type(exc).__name__}: {exc}")
            continue

        bfe = f", BFE {zone.base_flood_elevation} ft" if zone.base_flood_elevation else ""
        ok(
            f"  zone {zone.zone} ({zone.risk_class}) · SFHA={zone.in_sfha}"
            f"{bfe}{' (cached)' if zone.cached else ''}"
        )
        resolved += 1

    history = None
    try:
        history = flood_risk.fetch_flood_loss_history(zip_code)
        premium = (
            f"avg premium ${history.average_annual_premium:,.0f}"
            if history.average_annual_premium
            else "avg premium not published"
        )
        ok(
            f"ZIP {zip_code}: {history.claim_count:,} NFIP claim(s), "
            f"${history.total_paid:,.0f} paid across {history.claims_sampled:,} sampled · {premium}"
        )
        for caveat in history.caveats:
            print(f"{DIM}         {caveat}{RESET}")
    except Exception as exc:  # noqa: BLE001
        warn(f"OpenFEMA NFIP for {zip_code}: {type(exc).__name__}: {exc}")

    if resolved and history:
        print(f"\n{DIM}--- Flood impact on underwriting ---{RESET}")
        try:
            geocode = flood_risk.geocode_address(addresses[0])
            zone = flood_risk.lookup_flood_zone(
                geocode.latitude, geocode.longitude, use_cache=use_cache
            )
            assessment = flood_risk.assess_flood_risk(zone, arv=250_000, loss_history=history)
            print(
                f"  {zone.zone} on a $250,000 ARV: premium "
                f"${assessment['estimated_annual_premium']:,.0f}/yr "
                f"(measured={assessment['premium_measured']}), take-up "
                f"{assessment['insurance_take_up']:.0%}, modelled value impact "
                f"${assessment['capitalized_value_impact']:,.0f}"
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"Impact preview skipped: {exc}")

    return resolved > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zips", nargs="*", default=None, help="ZIP codes to check")
    parser.add_argument("--state", default="FL", help="State abbreviation for the index check")
    parser.add_argument(
        "--address",
        action="append",
        default=None,
        help="Address to flood-screen (repeatable). Defaults to a coastal sample.",
    )
    parser.add_argument("--skip-fema", action="store_true", help="Skip the FEMA checks")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the on-disk cache")
    args = parser.parse_args()

    zip_codes = args.zips or DEFAULT_ZIPS
    use_cache = not args.no_cache

    print("Verifying free public market-data sources")
    print(f"{DIM}  Census : {market_data.CENSUS_ACS_BASE}/{market_data.CENSUS_ACS_YEAR}/"
          f"{market_data.CENSUS_ACS_DATASET}{RESET}")
    print(f"{DIM}  FHFA   : {market_data.FHFA_ZIP5_URL}{RESET}")
    print(f"{DIM}  FEMA   : {flood_risk.FEMA_NFHL_URL}{RESET}")
    print(f"{DIM}  Cache  : {market_data.CACHE_DIR} ({'enabled' if use_cache else 'bypassed'}){RESET}")

    census_ok = verify_census(zip_codes, use_cache)
    fhfa_ok = verify_fhfa(zip_codes, args.state, use_cache)
    if census_ok:
        verify_plausibility(zip_codes[0], use_cache)

    fema_ok = True
    if not args.skip_fema:
        addresses = args.address or DEFAULT_ADDRESSES
        fema_ok = verify_fema(addresses, zip_codes[0], use_cache)

    print("\n" + "=" * 66)
    if census_ok and fhfa_ok and fema_ok:
        print(f"{GREEN}All sources are live. Underwriting will use measured appreciation and{RESET}")
        print(f"{GREEN}screen flood risk against FEMA.{RESET}")
        return 0
    if census_ok:
        missing = [
            name
            for name, live in (("FHFA", fhfa_ok), ("FEMA", fema_ok))
            if not live
        ]
        print(f"{YELLOW}Census is live; {' and '.join(missing)} is not.{RESET}")
        if not fhfa_ok:
            print(f"{YELLOW}Appreciation falls back to the built-in constant (measured=false).{RESET}")
        if not fema_ok:
            print(f"{YELLOW}Flood screening is unavailable — absence of a zone is NOT low risk.{RESET}")
        return 1
    print(f"{RED}Public market data is unreachable from this environment.{RESET}")
    print("If this is a 403 from an egress proxy, the hosts are blocked by network")
    print("policy rather than by the publishers — both are open, key-free APIs.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

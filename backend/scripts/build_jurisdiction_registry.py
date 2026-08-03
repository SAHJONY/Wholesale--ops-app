#!/usr/bin/env python3
"""Build a county registry from live catalogs, on a machine that can reach them.

The registry cannot be written from memory. A Socrata dataset is addressed by an
opaque four-by-four identifier and its columns are named by whoever published
it, so an entry composed from recall is a guess, and a guessed identifier
returns 404 -- which this pipeline reads as "no distress in this county"
rather than as a broken entry. Silence is the one failure mode that looks like
success, so entries are discovered and proven, never recalled.

This does the discovering and the proving in one pass:

1. Search the federated catalogs for datasets matching each category.
2. Fetch one real row from every candidate endpoint.
3. Read the actual column names off that row and propose a field map.
4. Emit only the candidates whose endpoint resolved and returned rows.

Everything it could not prove is reported with the reason, so a county that
publishes nothing machine-readable is distinguishable from one nobody searched.

Run it where outbound HTTPS works. It writes a file; it changes nothing live:

    python scripts/build_jurisdiction_registry.py --states FL GA --out registry.json
    python scripts/build_jurisdiction_registry.py --categories lis_pendens --limit 40
    DISTRESS_JURISDICTIONS_FILE=registry.json  # then point the backend at it

Column mapping is a proposal. The script matches real column names against the
patterns counties commonly use, and marks every entry `review_required` with the
fields it guessed, because a plausible column name is not a verified meaning.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.distress_discovery import (  # noqa: E402
    ARCGIS_SEARCH_URL,
    CATEGORY_QUERIES,
    SOCRATA_CATALOG_URL,
    STATE_NAMES,
    _matches_state,
)
from app.distress_providers import EXCLUDED_STATES, PROVIDERS_BY_ID  # noqa: E402

TIMEOUT = 25
GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

# Column-name patterns counties actually use, per canonical field. Ordered:
# the first pattern that matches a real column wins.
FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "address": (r"^(property_?)?(situs_?)?address", r"street_?address", r"^situs", r"location_?address"),
    "zip": (r"zip", r"postal"),
    "date": (r"date", r"_dt$", r"recorded", r"filed"),
    "case": (r"case", r"instrument", r"docket", r"file_?num", r"cert"),
    "amount": (r"amount", r"due", r"balance", r"owed", r"total"),
    "count": (r"count", r"years?", r"num_", r"_num$", r"qty"),
    "flag": (r"status", r"type", r"disposition", r"result", r"flag", r"active", r"open"),
}

# Which bucket a canonical field wants, decided by what the field means rather
# than by which pattern happens to match its name first. Order matters: a field
# named ``..._filed_at`` is a date, while ``..._filed`` on its own is a flag.
FIELD_BUCKETS: tuple[tuple[str, str], ...] = (
    (r"_at$|_date$|date_|scheduled_on", "date"),
    (r"amount|balance|due|owed", "amount"),
    (r"years?$|count$|_num$", "count"),
    (r"case|instrument|number|docket", "case"),
    (r"open$|scheduled$|filed$|recorded$|delinquent$|_flag$", "flag"),
)


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    request = urllib.request.Request(full, headers={
        "User-Agent": "sahjony-wholesale-os/registry-builder",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def _first_match(columns: list[str], patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        for column in columns:
            if re.search(pattern, column, re.I):
                return column
    return None


def propose_field_map(category: str, columns: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map canonical fields onto real columns, reporting which were guessed.

    Two rules keep a convenient guess from becoming a wrong fact:

    A field with no bucket, or a bucket with no matching column, is left
    unmapped. An earlier version fell back to "status" for anything unmatched,
    which mapped ``tax_amount_due`` onto a column named ``DELINQUENT_STATUS`` --
    a money field fed by a status string.

    A column may back only one field. The same version mapped both
    ``lis_pendens_filed`` and ``lis_pendens_filed_at`` onto ``date_filed``,
    quietly asserting that a boolean and a timestamp were the same column.
    """
    mapping: dict[str, str] = {}
    guessed: list[str] = []
    claimed: set[str] = set()

    for field in PROVIDERS_BY_ID[category].writable_fields:
        bucket = next((b for pattern, b in FIELD_BUCKETS if re.search(pattern, field, re.I)), None)
        if not bucket:
            continue
        available = [c for c in columns if c not in claimed]
        column = _first_match(available, FIELD_PATTERNS[bucket])
        if not column:
            continue
        mapping[field] = column
        claimed.add(column)
        guessed.append(field)
    return mapping, guessed


def sweep_socrata(query: str, limit: int) -> list[dict[str, Any]]:
    payload = _get(SOCRATA_CATALOG_URL, {"q": query, "only": "dataset", "limit": limit})
    out = []
    for item in payload.get("results") or []:
        resource, metadata = item.get("resource") or {}, item.get("metadata") or {}
        domain, dataset_id = metadata.get("domain"), resource.get("id")
        if not domain or not dataset_id:
            continue
        out.append({
            "transport": "socrata",
            "domain": domain,
            "dataset_id": dataset_id,
            "title": resource.get("name") or "",
            "description": (resource.get("description") or "")[:300],
            "endpoint": f"https://{domain}/resource/{dataset_id}.json",
        })
    return out


def sweep_arcgis(query: str, limit: int) -> list[dict[str, Any]]:
    payload = _get(ARCGIS_SEARCH_URL, {
        "q": f'{query} AND (type:"Feature Service")', "f": "json", "num": limit,
    })
    out = []
    for item in payload.get("results") or []:
        url = item.get("url") or ""
        if "FeatureServer" not in url:
            continue
        out.append({
            "transport": "arcgis",
            "domain": item.get("owner") or "",
            "dataset_id": item.get("id") or "",
            "title": item.get("title") or "",
            "description": (item.get("snippet") or "")[:300],
            "endpoint": f"{url.rstrip('/')}/0/query",
        })
    return out


def sample_columns(candidate: dict[str, Any]) -> tuple[list[str], str | None]:
    """Read one real row and return its column names, or why that failed."""
    try:
        if candidate["transport"] == "socrata":
            rows = _get(candidate["endpoint"], {"$limit": 1})
            if not isinstance(rows, list):
                return [], "endpoint did not return a row list"
            if not rows:
                return [], "endpoint resolved but is empty"
            return sorted(rows[0].keys()), None

        payload = _get(candidate["endpoint"], {
            "where": "1=1", "outFields": "*", "resultRecordCount": 1, "f": "json",
        })
        features = payload.get("features") or []
        if not features:
            return [], "feature service resolved but returned no features"
        return sorted((features[0].get("attributes") or {}).keys()), None
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - one bad dataset must not end the sweep
        return [], f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--states", nargs="*", default=[], help="Two-letter codes; omit for nationwide")
    parser.add_argument("--categories", nargs="*", default=[], help=f"Default: all of {', '.join(CATEGORY_QUERIES)}")
    parser.add_argument("--limit", type=int, default=20, help="Catalog hits per query (default 20)")
    parser.add_argument("--out", default="jurisdictions.json", help="Registry file to write")
    args = parser.parse_args()

    states = {s.strip().upper() for s in args.states if s.strip()}
    dropped = sorted(states & EXCLUDED_STATES)
    states -= EXCLUDED_STATES
    unknown = sorted(states - set(STATE_NAMES))
    if unknown:
        print(f"{RED}Unknown state codes: {', '.join(unknown)}{RESET}")
        return 2
    if dropped:
        print(f"{YELLOW}Skipping excluded states: {', '.join(dropped)}{RESET}")
    if args.states and not states:
        # An empty state set means nationwide. Reaching that by having every
        # requested state excluded would answer a question nobody asked, with a
        # sweep of the whole country.
        print(f"{RED}Every requested state is excluded from this workflow. Nothing to sweep.{RESET}")
        return 2

    categories = args.categories or [
        c for c in CATEGORY_QUERIES if PROVIDERS_BY_ID[c].access == "public_record"
    ]
    bad = sorted(set(categories) - set(CATEGORY_QUERIES))
    if bad:
        print(f"{RED}Unknown categories: {', '.join(bad)}{RESET}")
        return 2

    print(f"Building registry for {', '.join(sorted(states)) or 'every state'}")
    print(f"{DIM}  categories: {', '.join(categories)}{RESET}\n")

    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for category in categories:
        spec = PROVIDERS_BY_ID[category]
        print(f"{DIM}{category} ({spec.procedure}){RESET}")
        for query in CATEGORY_QUERIES[category]:
            for sweep in (sweep_socrata, sweep_arcgis):
                try:
                    hits = sweep(query, args.limit)
                except Exception as exc:  # noqa: BLE001
                    print(f"{RED}  catalog unreachable{RESET} {DIM}{query}: {type(exc).__name__}{RESET}")
                    continue

                for hit in hits:
                    if hit["endpoint"] in seen or not _matches_state(hit, states):
                        continue
                    seen.add(hit["endpoint"])

                    columns, failure = sample_columns(hit)
                    label = f"{hit['title'][:44]:46} {DIM}{hit['domain'][:26]}{RESET}"
                    if failure:
                        rejected.append({**hit, "category": category, "reason": failure})
                        print(f"{YELLOW}  skip{RESET} {label} {DIM}{failure}{RESET}")
                        continue

                    address = _first_match(columns, FIELD_PATTERNS["address"])
                    if not address:
                        rejected.append({**hit, "category": category, "reason": "no address-like column"})
                        print(f"{YELLOW}  skip{RESET} {label} {DIM}no address column{RESET}")
                        continue

                    field_map, guessed = propose_field_map(category, columns)
                    if not field_map:
                        rejected.append({**hit, "category": category, "reason": "no mappable columns"})
                        print(f"{YELLOW}  skip{RESET} {label} {DIM}no mappable columns{RESET}")
                        continue

                    entries.append({
                        "id": f"{hit['transport']}-{hit['dataset_id']}-{category}",
                        # Left for a human: the catalog rarely states these
                        # reliably, and inventing them is what this avoids.
                        "state": "REVIEW",
                        "county": hit["title"] or "REVIEW",
                        "category": category,
                        "procedure": spec.procedure,
                        "transport": hit["transport"],
                        "endpoint": hit["endpoint"],
                        "address_field": address,
                        "zip_field": _first_match(columns, FIELD_PATTERNS["zip"]),
                        "field_map": field_map,
                        "_verified": {
                            "endpoint_returned_a_row": True,
                            "observed_columns": columns[:40],
                        },
                        "_review_required": {
                            "state_and_county": "Set from the dataset's publisher; not inferred.",
                            "guessed_field_map": guessed,
                        },
                    })
                    print(f"{GREEN}  ok  {RESET} {label} {DIM}{len(field_map)} fields{RESET}")

    Path(args.out).write_text(json.dumps({
        "jurisdictions": entries,
        "_rejected": rejected,
        "_note": (
            "Every entry here resolved and returned a real row; observed_columns is what the "
            "endpoint actually carries. state and county are REVIEW placeholders on purpose, and "
            "the field map is proposed from column names, so confirm both before ingesting."
        ),
    }, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"{GREEN}{len(entries)} proven{RESET} · {YELLOW}{len(rejected)} rejected{RESET} → {args.out}")
    if entries:
        print(f"\n{DIM}Next: set state and county on each entry, confirm the field map,{RESET}")
        print(f"{DIM}then DISTRESS_JURISDICTIONS_FILE={args.out} and POST /distress-ingest/validate.{RESET}")
    else:
        print(f"\n{RED}Nothing was proven. If every line above says the catalog was unreachable,{RESET}")
        print(f"{RED}this machine cannot reach api.us.socrata.com or www.arcgis.com either.{RESET}")
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())

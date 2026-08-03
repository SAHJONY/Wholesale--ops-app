"""Free, verifiable public market data: Census ACS and FHFA House Price Index.

Both sources are U.S. Government works in the public domain, require no API key,
and impose no licence fee. They are used here to replace two things the
valuation engine was previously guessing at:

* **Market appreciation.** ``valuation.DEFAULT_MONTHLY_APPRECIATION`` was a
  hardcoded 0.35%/month. The FHFA House Price Index measures actual repeat-sale
  appreciation by ZIP, metro, and state.
* **Market plausibility.** Nothing checked whether a derived ARV was sane for
  its market. Census ACS publishes median owner-occupied home value by ZCTA.

Three rules govern everything in this module:

1. **Never fabricate.** A failed fetch raises or returns an explicit
   unavailability with a reason. It never silently substitutes a guess, and
   when a documented fallback constant *is* used, the result says so.
2. **Carry the uncertainty.** ACS figures are 5-year rolling estimates with
   published margins of error. A median of $180,000 ±$30,000 is different
   evidence from ±$3,000, and the caller gets to see which it has.
3. **Record provenance.** Every value carries its source, geography level,
   vintage, and retrieval time, so an underwriting decision stays auditable.

Known limitations, stated rather than hidden:

* **ZCTA is not ZIP.** Census publishes ZIP Code Tabulation Areas, which
  approximate USPS delivery areas but do not match them exactly. Boundaries
  differ, and some ZIPs (PO-box-only, for instance) have no ZCTA at all.
* **ACS 5-year estimates lag.** The 2023 release describes 2019-2023. It
  characterises a market, it does not price a house.
* **Neither source contains individual sales.** No free national source of
  arms-length comparable sales exists — see ``docs/FREE_DATA_SOURCES.md``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# --- Endpoints ------------------------------------------------------------
#
# Both are overridable so a deployment can point at a mirror, a cached
# artifact, or a newer vintage without a code change.

CENSUS_ACS_BASE = os.getenv("CENSUS_ACS_BASE_URL", "https://api.census.gov/data")
CENSUS_ACS_YEAR = os.getenv("CENSUS_ACS_YEAR", "2023")
CENSUS_ACS_DATASET = os.getenv("CENSUS_ACS_DATASET", "acs/acs5")

# A key is optional for the Census API and only raises the daily quota. The
# connector works without one.
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

# FHFA reorganised its site in 2024, so these defaults are treated as
# configuration rather than constants: parsing is by column name and a schema
# mismatch fails loudly instead of silently producing wrong appreciation.
FHFA_ZIP5_URL = os.getenv(
    "FHFA_HPI_ZIP5_URL",
    "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_bdl_zip5.csv",
)
FHFA_METRO_URL = os.getenv(
    "FHFA_HPI_METRO_URL",
    "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_metro.csv",
)
FHFA_STATE_URL = os.getenv(
    "FHFA_HPI_STATE_URL",
    "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_state.csv",
)

REQUEST_TIMEOUT_SECONDS = float(os.getenv("MARKET_DATA_TIMEOUT", "30"))
CACHE_DIR = Path(os.getenv("MARKET_DATA_CACHE_DIR", "/tmp/wholesale-market-data"))

# ACS is published annually and FHFA quarterly, so long TTLs are correct here
# and keep usage far inside the free tier.
ACS_CACHE_TTL_SECONDS = int(os.getenv("ACS_CACHE_TTL_SECONDS", str(30 * 86400)))
FHFA_CACHE_TTL_SECONDS = int(os.getenv("FHFA_CACHE_TTL_SECONDS", str(7 * 86400)))

# Fallback used only when no index can be fetched. Documented, conservative,
# and always reported as a fallback rather than presented as measured.
FALLBACK_ANNUAL_APPRECIATION = 0.042

# --- ACS variables --------------------------------------------------------
#
# Estimate variables end in E; the matching margin of error ends in M.

ACS_VARIABLES: dict[str, str] = {
    "B25077_001E": "median_home_value",
    "B25064_001E": "median_gross_rent",
    "B25003_001E": "occupied_units",
    "B25003_002E": "owner_occupied_units",
    "B25002_001E": "total_housing_units",
    "B25002_003E": "vacant_units",
    "B25035_001E": "median_year_built",
    "B19013_001E": "median_household_income",
}
ACS_MOE_FOR = {"B25077_001E": "B25077_001M", "B25064_001E": "B25064_001M"}

# Census "jam values": negative sentinels meaning the estimate could not be
# published, not an actual negative dollar figure. Treating -666666666 as a
# number is the classic way to corrupt a Census integration.
CENSUS_JAM_THRESHOLD = -100_000_000


class MarketDataError(RuntimeError):
    """Base class for market-data failures."""


class MarketDataUnavailable(MarketDataError):
    """The source could not be reached, or published no value for this area."""


class MarketDataSchemaError(MarketDataError):
    """The source responded, but not in the shape this connector understands."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Disk cache -----------------------------------------------------------


def _cache_path(name: str) -> Path:
    return CACHE_DIR / name


def _read_cache(name: str, ttl_seconds: int) -> Any | None:
    path = _cache_path(name)
    try:
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > ttl_seconds:
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        # A corrupt or unreadable cache entry must never break a live request.
        return None


def _write_cache(name: str, payload: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(name).write_text(json.dumps(payload))
    except OSError as exc:
        logger.warning("Could not write market-data cache %s: %s", name, exc)


def _get(url: str, params: dict | None = None, *, client: httpx.Client | None = None) -> httpx.Response:
    owned = client is None
    client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise MarketDataUnavailable(f"{type(exc).__name__} fetching {url}: {exc}") from exc
    finally:
        if owned:
            client.close()
    if response.status_code != 200:
        raise MarketDataUnavailable(
            f"{url} returned HTTP {response.status_code}. If this is 403 from an egress "
            "proxy, the host is blocked by network policy rather than by the publisher."
        )
    return response


# --- Census ACS -----------------------------------------------------------


@dataclass
class MarketContext:
    """Census ACS housing characteristics for one ZCTA."""

    zip_code: str
    median_home_value: float | None = None
    median_home_value_moe: float | None = None
    median_gross_rent: float | None = None
    median_gross_rent_moe: float | None = None
    owner_occupancy_rate: float | None = None
    vacancy_rate: float | None = None
    median_year_built: int | None = None
    median_household_income: float | None = None
    total_housing_units: int | None = None
    source: str = "US Census Bureau American Community Survey 5-Year Estimates"
    dataset: str = ""
    vintage: str = ""
    geography: str = "ZIP Code Tabulation Area"
    retrieved_at: str = ""
    cached: bool = False
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "zip_code": self.zip_code,
            "median_home_value": self.median_home_value,
            "median_home_value_moe": self.median_home_value_moe,
            "median_gross_rent": self.median_gross_rent,
            "median_gross_rent_moe": self.median_gross_rent_moe,
            "owner_occupancy_rate": self.owner_occupancy_rate,
            "vacancy_rate": self.vacancy_rate,
            "median_year_built": self.median_year_built,
            "median_household_income": self.median_household_income,
            "total_housing_units": self.total_housing_units,
            "provenance": {
                "source": self.source,
                "dataset": self.dataset,
                "vintage": self.vintage,
                "geography": self.geography,
                "retrieved_at": self.retrieved_at,
                "cached": self.cached,
                "licence": "U.S. Government work, public domain",
                "api_key_required": False,
            },
            "caveats": self.caveats,
        }


def _census_number(raw: Any) -> float | None:
    """Parse a Census value, mapping jam sentinels to None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.upper() in {"NULL", "N/A", "NONE"}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= CENSUS_JAM_THRESHOLD:
        # -666666666 and friends mean "estimate not available", never a value.
        return None
    return value


def fetch_market_context(
    zip_code: str,
    *,
    year: str | None = None,
    client: httpx.Client | None = None,
    use_cache: bool = True,
) -> MarketContext:
    """Fetch ACS housing characteristics for a ZIP Code Tabulation Area.

    Raises :class:`MarketDataUnavailable` when the area has no published data,
    which is a real and common outcome for low-population and PO-box-only ZIPs.
    """
    zip_code = str(zip_code).strip()
    if not (len(zip_code) == 5 and zip_code.isdigit()):
        raise ValueError(f"Expected a five-digit ZIP code, got {zip_code!r}")

    year = year or CENSUS_ACS_YEAR
    cache_key = f"acs-{year}-{zip_code}.json"

    if use_cache:
        cached = _read_cache(cache_key, ACS_CACHE_TTL_SECONDS)
        if cached is not None:
            context = _context_from_row(zip_code, cached["header"], cached["row"], year)
            context.cached = True
            return context

    variables = list(ACS_VARIABLES) + list(ACS_MOE_FOR.values())
    params = {
        "get": "NAME," + ",".join(variables),
        "for": f"zip code tabulation area:{zip_code}",
    }
    if CENSUS_API_KEY:
        params["key"] = CENSUS_API_KEY

    url = f"{CENSUS_ACS_BASE}/{year}/{CENSUS_ACS_DATASET}"
    response = _get(url, params, client=client)

    try:
        payload = response.json()
    except ValueError as exc:
        raise MarketDataSchemaError(f"Census returned non-JSON for {zip_code}") from exc

    if not isinstance(payload, list) or len(payload) < 2:
        raise MarketDataUnavailable(
            f"Census published no ACS {year} data for ZCTA {zip_code}. Low-population "
            "and PO-box-only ZIP codes frequently have no tabulation area."
        )

    header, row = payload[0], payload[1]
    if not isinstance(header, list) or not isinstance(row, list):
        raise MarketDataSchemaError("Census response was not the expected array-of-arrays")

    if use_cache:
        _write_cache(cache_key, {"header": header, "row": row})
    return _context_from_row(zip_code, header, row, year)


def _context_from_row(zip_code: str, header: list, row: list, year: str) -> MarketContext:
    """Map a Census response row onto :class:`MarketContext` by column name."""
    if len(header) != len(row):
        raise MarketDataSchemaError("Census header and data row lengths differ")
    values = dict(zip(header, row))

    missing = [name for name in ACS_VARIABLES if name not in values]
    if missing:
        raise MarketDataSchemaError(
            f"Census response is missing expected variables: {', '.join(missing)}"
        )

    numbers = {
        field_name: _census_number(values.get(variable))
        for variable, field_name in ACS_VARIABLES.items()
    }

    occupied = numbers["occupied_units"]
    owner_occupied = numbers["owner_occupied_units"]
    total_units = numbers["total_housing_units"]
    vacant = numbers["vacant_units"]

    owner_rate = (
        round(owner_occupied / occupied, 4) if occupied and owner_occupied is not None and occupied > 0 else None
    )
    vacancy_rate = (
        round(vacant / total_units, 4) if total_units and vacant is not None and total_units > 0 else None
    )

    caveats = [
        "ZIP Code Tabulation Areas approximate USPS ZIP codes; boundaries are not identical.",
        f"ACS {year} 5-year estimates describe a rolling five-year window, not the current month.",
    ]
    value_moe = _census_number(values.get(ACS_MOE_FOR["B25077_001E"]))
    median_value = numbers["median_home_value"]
    if median_value and value_moe and median_value > 0 and value_moe / median_value > 0.15:
        caveats.append(
            f"Median home value has a wide margin of error (±${value_moe:,.0f} on "
            f"${median_value:,.0f}); treat it as a weak market signal."
        )
    if median_value is None:
        caveats.append("Census published no median home value for this area.")

    return MarketContext(
        zip_code=zip_code,
        median_home_value=median_value,
        median_home_value_moe=value_moe,
        median_gross_rent=numbers["median_gross_rent"],
        median_gross_rent_moe=_census_number(values.get(ACS_MOE_FOR["B25064_001E"])),
        owner_occupancy_rate=owner_rate,
        vacancy_rate=vacancy_rate,
        median_year_built=int(numbers["median_year_built"]) if numbers["median_year_built"] else None,
        median_household_income=numbers["median_household_income"],
        total_housing_units=int(total_units) if total_units else None,
        dataset=f"{CENSUS_ACS_DATASET} {year}",
        vintage=year,
        retrieved_at=_now().isoformat(),
        caveats=caveats,
    )


# --- FHFA House Price Index ----------------------------------------------


@dataclass
class AppreciationRate:
    """A measured (or explicitly fallback) house-price appreciation rate."""

    annual_rate: float
    monthly_rate: float
    level: str  # zip | metro | state | fallback
    area: str
    period: str
    measured: bool
    source: str
    retrieved_at: str
    cached: bool = False
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "annual_rate": round(self.annual_rate, 5),
            "monthly_rate": round(self.monthly_rate, 6),
            "level": self.level,
            "area": self.area,
            "period": self.period,
            "measured": self.measured,
            "provenance": {
                "source": self.source,
                "retrieved_at": self.retrieved_at,
                "cached": self.cached,
                "licence": "U.S. Government work, public domain",
                "api_key_required": False,
            },
            "note": self.note,
        }


def _annual_to_monthly(annual_rate: float) -> float:
    """Convert an annual rate to its compounding monthly equivalent."""
    return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


def _find_column(header: list[str], *candidates: str) -> str | None:
    """Locate a column by fuzzy name match, so minor header edits don't break parsing."""
    normalised = {name.strip().lower().replace("_", " "): name for name in header}
    for candidate in candidates:
        key = candidate.strip().lower().replace("_", " ")
        if key in normalised:
            return normalised[key]
    for candidate in candidates:
        key = candidate.strip().lower().replace("_", " ")
        for existing_key, original in normalised.items():
            if key in existing_key:
                return original
    return None


def parse_fhfa_zip5(csv_text: str, zip_code: str) -> tuple[float, str]:
    """Parse the FHFA five-digit-ZIP annual index for one ZIP's latest change.

    Returns ``(annual_rate, period)``. Columns are located by name so a header
    reorder does not silently shift which column is read as appreciation.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    header = reader.fieldnames or []
    if not header:
        raise MarketDataSchemaError("FHFA ZIP5 file has no header row")

    zip_column = _find_column(header, "Five-Digit ZIP Code", "zip code", "zip")
    year_column = _find_column(header, "Year")
    change_column = _find_column(header, "Annual Change (%)", "annual change")
    if not (zip_column and year_column and change_column):
        raise MarketDataSchemaError(
            f"FHFA ZIP5 header not recognised (got: {', '.join(header)}). "
            "Set FHFA_HPI_ZIP5_URL to a matching dataset or update the parser."
        )

    target = str(zip_code).strip().lstrip("0")
    best_year = None
    best_change = None
    for row in reader:
        raw_zip = str(row.get(zip_column) or "").strip()
        if raw_zip.lstrip("0") != target:
            continue
        try:
            year = int(str(row.get(year_column)).strip())
            change = float(str(row.get(change_column)).strip())
        except (TypeError, ValueError):
            continue
        if best_year is None or year > best_year:
            best_year, best_change = year, change

    if best_year is None or best_change is None:
        raise MarketDataUnavailable(f"FHFA publishes no ZIP-level index for {zip_code}")
    # FHFA reports annual change as a percentage, not a fraction.
    return best_change / 100.0, str(best_year)


def parse_fhfa_periodic(csv_text: str, area_key: str, *, area_columns: tuple[str, ...]) -> tuple[float, str]:
    """Parse a quarterly FHFA file (state or metro) into a year-over-year rate.

    Quarterly files publish an index level rather than an annual change, so the
    rate is computed from the index four quarters apart — which is the correct
    year-over-year comparison and avoids seasonal distortion.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    header = reader.fieldnames or []
    if not header:
        raise MarketDataSchemaError("FHFA file has no header row")

    area_column = _find_column(header, *area_columns)
    year_column = _find_column(header, "Year", "yr")
    quarter_column = _find_column(header, "Quarter", "qtr", "period")
    index_column = _find_column(header, "Index (NSA)", "index nsa", "index_nsa", "index", "HPI")
    if not (area_column and year_column and index_column):
        raise MarketDataSchemaError(
            f"FHFA header not recognised (got: {', '.join(header)})."
        )

    target = str(area_key).strip().upper()
    series: list[tuple[tuple[int, int], float]] = []
    for row in reader:
        if str(row.get(area_column) or "").strip().upper() != target:
            continue
        try:
            year = int(str(row.get(year_column)).strip())
            quarter = int(str(row.get(quarter_column)).strip()) if quarter_column else 4
            index = float(str(row.get(index_column)).strip())
        except (TypeError, ValueError):
            continue
        if index > 0:
            series.append(((year, quarter), index))

    if len(series) < 5:
        raise MarketDataUnavailable(
            f"FHFA has fewer than five quarters of index data for {area_key}"
        )

    series.sort(key=lambda item: item[0])
    (latest_period, latest_index) = series[-1]
    (prior_period, prior_index) = series[-5]
    rate = (latest_index / prior_index) - 1.0
    return rate, f"{latest_period[0]}Q{latest_period[1]} vs {prior_period[0]}Q{prior_period[1]}"


def _fetch_text(url: str, cache_key: str, client: httpx.Client | None, use_cache: bool) -> tuple[str, bool]:
    if use_cache:
        cached = _read_cache(cache_key, FHFA_CACHE_TTL_SECONDS)
        if isinstance(cached, dict) and "text" in cached:
            return cached["text"], True
    text = _get(url, client=client).text
    if use_cache:
        _write_cache(cache_key, {"text": text})
    return text, False


def fetch_appreciation(
    *,
    zip_code: str | None = None,
    state: str | None = None,
    metro_code: str | None = None,
    client: httpx.Client | None = None,
    use_cache: bool = True,
    allow_fallback: bool = True,
) -> AppreciationRate:
    """Resolve an appreciation rate, preferring the most local measurement.

    Tries ZIP, then metro, then state. Each level is a real FHFA measurement;
    only the final fallback is a constant, and it is labelled ``measured=False``
    so a caller can never mistake it for data.
    """
    attempts: list[str] = []

    if zip_code:
        try:
            text, cached = _fetch_text(FHFA_ZIP5_URL, "fhfa-zip5.json", client, use_cache)
            rate, period = parse_fhfa_zip5(text, zip_code)
            return AppreciationRate(
                annual_rate=rate,
                monthly_rate=_annual_to_monthly(rate),
                level="zip",
                area=str(zip_code),
                period=period,
                measured=True,
                source="FHFA House Price Index, five-digit ZIP (annual, developmental)",
                retrieved_at=_now().isoformat(),
                cached=cached,
                note="FHFA labels the ZIP-level index developmental; it is annual, not quarterly.",
            )
        except MarketDataError as exc:
            attempts.append(f"zip: {exc}")

    if metro_code:
        try:
            text, cached = _fetch_text(FHFA_METRO_URL, "fhfa-metro.json", client, use_cache)
            rate, period = parse_fhfa_periodic(
                text, metro_code, area_columns=("CBSA", "Metropolitan Statistical Area", "metro")
            )
            return AppreciationRate(
                annual_rate=rate,
                monthly_rate=_annual_to_monthly(rate),
                level="metro",
                area=str(metro_code),
                period=period,
                measured=True,
                source="FHFA House Price Index, metropolitan statistical area (quarterly)",
                retrieved_at=_now().isoformat(),
                cached=cached,
            )
        except MarketDataError as exc:
            attempts.append(f"metro: {exc}")

    if state:
        try:
            text, cached = _fetch_text(FHFA_STATE_URL, "fhfa-state.json", client, use_cache)
            rate, period = parse_fhfa_periodic(text, state, area_columns=("State", "state_abbr"))
            return AppreciationRate(
                annual_rate=rate,
                monthly_rate=_annual_to_monthly(rate),
                level="state",
                area=str(state).upper(),
                period=period,
                measured=True,
                source="FHFA House Price Index, state (quarterly)",
                retrieved_at=_now().isoformat(),
                cached=cached,
            )
        except MarketDataError as exc:
            attempts.append(f"state: {exc}")

    if not allow_fallback:
        raise MarketDataUnavailable(
            "No FHFA index could be resolved. Attempts: " + "; ".join(attempts or ["none requested"])
        )

    return AppreciationRate(
        annual_rate=FALLBACK_ANNUAL_APPRECIATION,
        monthly_rate=_annual_to_monthly(FALLBACK_ANNUAL_APPRECIATION),
        level="fallback",
        area=str(zip_code or state or metro_code or "unknown"),
        period="n/a",
        measured=False,
        source="Documented constant — no FHFA index was reachable",
        retrieved_at=_now().isoformat(),
        note=(
            "This rate is NOT measured. Comparable time adjustments derived from it are "
            "assumptions. Attempts: " + "; ".join(attempts or ["no geography supplied"])
        ),
    )


# --- Plausibility ---------------------------------------------------------


def check_arv_plausibility(arv: float, context: MarketContext) -> dict:
    """Sanity-check a derived ARV against the area's median home value.

    This catches the failure the comparable-sales engine cannot catch on its
    own: internally consistent comparables drawn from the wrong neighbourhood,
    or a decimal-place error in a sale price. It is a screen, not a valuation —
    a genuinely renovated house in a tired ZIP *should* exceed the median.
    """
    median = context.median_home_value
    if not median or median <= 0:
        return {
            "checked": False,
            "reason": f"Census published no median home value for ZCTA {context.zip_code}",
        }

    ratio = arv / median
    moe = context.median_home_value_moe or 0.0

    # Widen the plausible band when the Census estimate is itself imprecise.
    # The widening is multiplicative because the band is expressed as a ratio:
    # applying it additively would push the lower bound toward zero and make
    # the low-side screen useless.
    relative_moe = min(0.35, (moe / median) if moe else 0.0)
    widen = 1.0 + relative_moe
    high_bound = 2.5 * widen
    low_bound = 0.35 / widen

    if ratio > high_bound:
        verdict, guidance = "implausible_high", (
            f"ARV is {ratio:.1f}x the area median. Verify the comparables are in this "
            "market and that no sale price has a decimal error."
        )
    elif ratio < low_bound:
        verdict, guidance = "implausible_low", (
            f"ARV is {ratio:.2f}x the area median. Verify the comparables are not all "
            "distressed or non-arms-length sales."
        )
    elif ratio > 1.8:
        verdict, guidance = "high", (
            f"ARV is {ratio:.1f}x the area median — defensible for a renovated property, "
            "but confirm the comparables reflect the post-repair condition."
        )
    elif ratio < 0.6:
        verdict, guidance = "low", (
            f"ARV is {ratio:.2f}x the area median — confirm the comparables are not "
            "skewed by distressed sales."
        )
    else:
        verdict, guidance = "consistent", "ARV is consistent with the area median."

    return {
        "checked": True,
        "verdict": verdict,
        "guidance": guidance,
        "arv_to_median_ratio": round(ratio, 3),
        "plausible_band": {"low": round(low_bound, 3), "high": round(high_bound, 3)},
        "area_median_home_value": median,
        "area_median_moe": moe or None,
        "geography": f"ZCTA {context.zip_code}",
        "vintage": context.vintage,
        "note": (
            "Census medians cover all owner-occupied homes regardless of size or condition, "
            "so this is a screen for gross error, not a valuation."
        ),
    }


def source_registry() -> list[dict]:
    """The free sources this module uses, for the console and audit trail."""
    return [
        {
            "id": "census_acs",
            "name": "U.S. Census Bureau — American Community Survey 5-Year Estimates",
            "url": f"{CENSUS_ACS_BASE}/{CENSUS_ACS_YEAR}/{CENSUS_ACS_DATASET}",
            "cost": "free",
            "api_key_required": False,
            "api_key_configured": bool(CENSUS_API_KEY),
            "licence": "U.S. Government work, public domain",
            "provides": [
                "median home value (with margin of error)",
                "median gross rent",
                "owner-occupancy rate",
                "vacancy rate",
                "median year built",
                "median household income",
            ],
            "does_not_provide": ["individual sales", "ownership", "liens", "property condition"],
            "geography": "ZIP Code Tabulation Area (approximates USPS ZIP)",
        },
        {
            "id": "fhfa_hpi",
            "name": "Federal Housing Finance Agency — House Price Index",
            "url": FHFA_STATE_URL,
            "cost": "free",
            "api_key_required": False,
            "api_key_configured": False,
            "licence": "U.S. Government work, public domain",
            "provides": ["repeat-sale house price appreciation by ZIP, metro, and state"],
            "does_not_provide": ["individual sales", "property-level valuation"],
            "geography": "five-digit ZIP (annual), CBSA and state (quarterly)",
        },
    ]

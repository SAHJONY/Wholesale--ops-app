"""FEMA flood risk: zone lookup, realized losses, and underwriting impact.

`public_data_providers.py` has listed the FEMA National Flood Hazard Layer as a
provider since the framework was written, but nothing ever called it. This is
that connector.

Flood zone is not decoration on a property record — it changes the economics of
the deal. A property inside a Special Flood Hazard Area requires flood insurance
for any federally-backed mortgage, which is a permanent annual cost the eventual
retail buyer capitalises into what they will pay. That shrinks the buyer pool
and the price, which is exactly the sort of thing a wholesale desk needs to know
*before* contracting, not at closing.

Three free sources, none requiring an API key:

* **FEMA NFHL** (ArcGIS REST) — the flood zone polygon covering a coordinate.
* **U.S. Census Geocoder** — address to coordinate, so a lead with only a street
  address can still be screened.
* **OpenFEMA NFIP** — actual paid flood claims and actual average policy
  premiums, which turn a zone letter into a dollar figure grounded in what this
  ZIP has really paid.

The value impact is *derived*, not asserted: a measured annual premium
capitalised at a documented rate. Where the premium is measured the derivation
rests on real data, and where it is not the result says so.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from .market_data import (
    FHFA_CACHE_TTL_SECONDS,
    MarketDataError,
    MarketDataSchemaError,
    MarketDataUnavailable,
    _read_cache,
    _write_cache,
)

logger = logging.getLogger(__name__)

# --- Endpoints ------------------------------------------------------------
#
# Layer 28 of the public NFHL MapServer is the flood hazard zone polygon layer
# (S_FLD_HAZ_AR). The env var matches the name the provider framework already
# reserved for it.

FEMA_NFHL_URL = os.getenv(
    "FEMA_NFHL_URL",
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
)
FEMA_NFHL_ZONE_LAYER = os.getenv("FEMA_NFHL_ZONE_LAYER", "28")

CENSUS_GEOCODER_URL = os.getenv(
    "CENSUS_GEOCODER_URL",
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
)
CENSUS_GEOCODER_BENCHMARK = os.getenv("CENSUS_GEOCODER_BENCHMARK", "Public_AR_Current")

OPENFEMA_BASE = os.getenv("OPENFEMA_BASE_URL", "https://www.fema.gov/api/open/v2")

REQUEST_TIMEOUT_SECONDS = float(os.getenv("FLOOD_DATA_TIMEOUT", "30"))
NFIP_CLAIM_PAGE_SIZE = int(os.getenv("NFIP_CLAIM_PAGE_SIZE", "1000"))

# --- Zone classification --------------------------------------------------
#
# Special Flood Hazard Areas are the 1%-annual-chance ("100-year") zones. Any
# federally-backed mortgage on a property in one requires flood insurance.

SFHA_ZONES = {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE", "A1-30", "V1-30"}
COASTAL_HIGH_HAZARD_ZONES = {"V", "VE", "V1-30"}
MODERATE_ZONES = {"X"}  # shaded X: 0.2% annual chance, distinguished via subtype
UNDETERMINED_ZONES = {"D"}

# FEMA uses -9999 where a base flood elevation does not apply. Read as a number
# it becomes an elevation 9,999 feet below sea level.
BFE_SENTINELS = {-9999, -9999.0, -8888, -8888.0}

# Capitalisation rate used to convert a recurring annual insurance premium into
# a one-off value impact. A retail buyer prices a permanent cost as its present
# value; 7% is a conventional residential capitalisation rate. Configurable
# because it is a modelling assumption, not a measurement.
INSURANCE_CAPITALIZATION_RATE = float(os.getenv("FLOOD_INSURANCE_CAP_RATE", "0.07"))

# Ceiling on the modelled impact, so a single outlier premium cannot swamp a
# valuation.
MAX_VALUE_IMPACT_SHARE = 0.25

# Share of buyers who will actually carry flood insurance, by risk class. This
# is what makes the premium capitalise into price: outside an SFHA, coverage is
# optional and most buyers decline it, so the premium is not a cost the market
# prices in. Capitalising a premium in a minimal-risk zone would invent a
# discount that does not exist.
INSURANCE_TAKE_UP = {
    "coastal_high_hazard": 1.0,  # mandatory with federally-backed financing
    "high": 1.0,                 # mandatory with federally-backed financing
    "moderate": 0.4,             # optional; commonly carried in the 0.2% floodplain
    "undetermined": 0.5,         # unstudied — price roughly half the exposure
    "minimal": 0.0,
    "unmapped": 0.0,
}

# Used only when OpenFEMA publishes no average premium for the area. Order of
# magnitude, deliberately conservative, and always reported as an estimate.
ESTIMATED_ANNUAL_PREMIUM = {
    "coastal_high_hazard": 3_200.0,
    "high": 1_700.0,
    "moderate": 700.0,
    "minimal": 500.0,
    "undetermined": 1_000.0,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(url: str, params: dict, *, client: httpx.Client | None = None) -> httpx.Response:
    owned = client is None
    client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    try:
        response = client.get(url, params=params, headers={"User-Agent": "sahjony-wholesale-os/1.0"})
    except httpx.HTTPError as exc:
        raise MarketDataUnavailable(f"{type(exc).__name__} fetching {url}: {exc}") from exc
    finally:
        if owned:
            client.close()
    if response.status_code != 200:
        raise MarketDataUnavailable(
            f"{url} returned HTTP {response.status_code}. If this is 403 from an egress "
            "proxy, the host is blocked by network policy rather than by FEMA."
        )
    return response


def _number(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return None if value in BFE_SENTINELS else value


# --- Geocoding ------------------------------------------------------------


@dataclass
class GeocodeResult:
    latitude: float
    longitude: float
    matched_address: str
    source: str = "U.S. Census Bureau Geocoder"

    def as_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "matched_address": self.matched_address,
            "source": self.source,
        }


def geocode_address(address: str, *, client: httpx.Client | None = None) -> GeocodeResult:
    """Resolve a one-line address to coordinates using the free Census geocoder.

    Raises :class:`MarketDataUnavailable` when the address cannot be matched,
    which is a real outcome for new construction and rural routes — and far
    better than silently screening the wrong coordinate.
    """
    address = str(address or "").strip()
    if not address:
        raise ValueError("An address is required")

    response = _get(
        CENSUS_GEOCODER_URL,
        {"address": address, "benchmark": CENSUS_GEOCODER_BENCHMARK, "format": "json"},
        client=client,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise MarketDataSchemaError("Census geocoder returned non-JSON") from exc

    matches = ((payload or {}).get("result") or {}).get("addressMatches") or []
    if not matches:
        raise MarketDataUnavailable(f"Census geocoder found no match for {address!r}")

    match = matches[0]
    coordinates = match.get("coordinates") or {}
    longitude, latitude = coordinates.get("x"), coordinates.get("y")
    if longitude is None or latitude is None:
        raise MarketDataSchemaError("Census geocoder match carried no coordinates")

    return GeocodeResult(
        latitude=float(latitude),
        longitude=float(longitude),
        matched_address=str(match.get("matchedAddress") or address),
    )


# --- NFHL flood zone ------------------------------------------------------


@dataclass
class FloodZone:
    """The FEMA flood hazard zone covering a coordinate."""

    zone: str
    zone_subtype: str | None
    in_sfha: bool
    risk_class: str
    base_flood_elevation: float | None
    depth: float | None
    firm_id: str | None
    latitude: float
    longitude: float
    mandatory_insurance: bool
    description: str
    source: str = "FEMA National Flood Hazard Layer"
    retrieved_at: str = ""
    cached: bool = False
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "zone": self.zone,
            "zone_subtype": self.zone_subtype,
            "in_sfha": self.in_sfha,
            "risk_class": self.risk_class,
            "mandatory_insurance": self.mandatory_insurance,
            "base_flood_elevation": self.base_flood_elevation,
            "depth": self.depth,
            "firm_id": self.firm_id,
            "description": self.description,
            "coordinates": {"latitude": self.latitude, "longitude": self.longitude},
            "provenance": {
                "source": self.source,
                "retrieved_at": self.retrieved_at,
                "cached": self.cached,
                "licence": "U.S. Government work, public domain",
                "api_key_required": False,
            },
            "caveats": self.caveats,
        }


def classify_zone(zone: str, subtype: str | None) -> tuple[str, bool, str]:
    """Map a FEMA zone code to (risk_class, in_sfha, description).

    The 0.2%-annual-chance area is reported as zone ``X`` with a distinguishing
    subtype, so zone alone is not enough to separate moderate from minimal risk.
    """
    code = str(zone or "").strip().upper()
    sub = str(subtype or "").strip().upper()

    if code in COASTAL_HIGH_HAZARD_ZONES:
        return (
            "coastal_high_hazard",
            True,
            "Coastal high-hazard area subject to storm-induced wave action. Highest "
            "insurance cost and the most constrained resale market.",
        )
    if code in SFHA_ZONES:
        return (
            "high",
            True,
            "Special Flood Hazard Area with a 1% annual chance of flooding. Flood "
            "insurance is mandatory for federally-backed mortgages.",
        )
    if code in UNDETERMINED_ZONES:
        return (
            "undetermined",
            False,
            "Flood hazard undetermined. FEMA has not studied this area; absence of a "
            "mapped zone is not evidence of low risk.",
        )
    if code in MODERATE_ZONES:
        if "0.2" in sub or "500" in sub:
            return (
                "moderate",
                False,
                "0.2% annual chance (500-year) flood hazard. Insurance is not mandatory "
                "but is materially cheaper to carry than in an SFHA.",
            )
        return (
            "minimal",
            False,
            "Area of minimal flood hazard outside the 0.2% annual chance floodplain.",
        )
    if code in {"AREA NOT INCLUDED", "OPEN WATER", ""}:
        return (
            "unmapped",
            False,
            "No FEMA flood hazard mapping at this location.",
        )
    return (
        "undetermined",
        False,
        f"Unrecognised FEMA zone code {code!r}. Verify against the FEMA Map Service Center.",
    )


def lookup_flood_zone(
    latitude: float,
    longitude: float,
    *,
    client: httpx.Client | None = None,
    use_cache: bool = True,
) -> FloodZone:
    """Look up the FEMA flood zone covering a coordinate."""
    latitude, longitude = float(latitude), float(longitude)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError(f"Coordinates out of range: {latitude}, {longitude}")

    # Five decimal places is roughly a metre — precise enough for a parcel and
    # coarse enough that nearby lookups share a cache entry.
    cache_key = f"nfhl-{latitude:.5f}-{longitude:.5f}.json"
    if use_cache:
        cached = _read_cache(cache_key, FHFA_CACHE_TTL_SECONDS)
        if cached is not None:
            zone = _zone_from_attributes(cached, latitude, longitude)
            zone.cached = True
            return zone

    url = f"{FEMA_NFHL_URL}/{FEMA_NFHL_ZONE_LAYER}/query"
    params = {
        "geometry": f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DEPTH,DFIRM_ID",
        "returnGeometry": "false",
        "f": "json",
    }
    response = _get(url, params, client=client)

    try:
        payload = response.json()
    except ValueError as exc:
        raise MarketDataSchemaError("FEMA NFHL returned non-JSON") from exc

    # ArcGIS reports its own errors inside an HTTP 200 body. Skipping this check
    # is the classic way to treat a service failure as "no flood risk".
    if isinstance(payload, dict) and "error" in payload:
        error = payload["error"] or {}
        raise MarketDataUnavailable(
            f"FEMA NFHL error {error.get('code')}: {error.get('message')}"
        )

    features = (payload or {}).get("features")
    if features is None:
        raise MarketDataSchemaError("FEMA NFHL response contained no 'features' key")
    if not features:
        raise MarketDataUnavailable(
            f"FEMA has no mapped flood hazard area at {latitude}, {longitude}. "
            "Unmapped is not the same as low risk — verify at the FEMA Map Service Center."
        )

    attributes = features[0].get("attributes") or {}
    if use_cache:
        _write_cache(cache_key, attributes)
    return _zone_from_attributes(attributes, latitude, longitude)


def _zone_from_attributes(attributes: dict, latitude: float, longitude: float) -> FloodZone:
    zone_code = str(attributes.get("FLD_ZONE") or "").strip()
    subtype = str(attributes.get("ZONE_SUBTY") or "").strip() or None
    risk_class, derived_sfha, description = classify_zone(zone_code, subtype)

    # Prefer FEMA's own SFHA flag where present; fall back to zone-code logic.
    sfha_flag = str(attributes.get("SFHA_TF") or "").strip().upper()
    in_sfha = derived_sfha if sfha_flag not in {"T", "F"} else sfha_flag == "T"

    caveats = [
        "Flood zone reflects the effective FEMA map, which may predate recent "
        "construction, elevation certificates, or a pending map revision.",
        "A zone determination is not a substitute for an elevation certificate or a "
        "lender's flood determination at closing.",
    ]
    if risk_class == "undetermined":
        caveats.append("Unstudied or unrecognised zone; treat the risk as unknown rather than low.")

    return FloodZone(
        zone=zone_code or "UNKNOWN",
        zone_subtype=subtype,
        in_sfha=in_sfha,
        risk_class=risk_class,
        base_flood_elevation=_number(attributes.get("STATIC_BFE")),
        depth=_number(attributes.get("DEPTH")),
        firm_id=str(attributes.get("DFIRM_ID") or "").strip() or None,
        latitude=latitude,
        longitude=longitude,
        mandatory_insurance=in_sfha,
        description=description,
        retrieved_at=_now().isoformat(),
        caveats=caveats,
    )


# --- OpenFEMA NFIP --------------------------------------------------------


@dataclass
class FloodLossHistory:
    """Realized flood losses and actual policy costs for an area."""

    zip_code: str
    claim_count: int
    claims_sampled: int
    total_paid: float
    average_paid: float | None
    most_recent_loss_year: int | None
    average_annual_premium: float | None
    policy_count: int | None
    truncated: bool
    source: str = "OpenFEMA NFIP claims and policies"
    retrieved_at: str = ""
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "zip_code": self.zip_code,
            "claim_count": self.claim_count,
            "claims_sampled": self.claims_sampled,
            "total_paid": round(self.total_paid, 2),
            "average_paid": round(self.average_paid, 2) if self.average_paid else None,
            "most_recent_loss_year": self.most_recent_loss_year,
            "average_annual_premium": (
                round(self.average_annual_premium, 2) if self.average_annual_premium else None
            ),
            "policy_count": self.policy_count,
            "truncated": self.truncated,
            "provenance": {
                "source": self.source,
                "retrieved_at": self.retrieved_at,
                "licence": "U.S. Government work, public domain",
                "api_key_required": False,
            },
            "caveats": self.caveats,
        }


def fetch_flood_loss_history(
    zip_code: str, *, client: httpx.Client | None = None
) -> FloodLossHistory:
    """Fetch realized NFIP claims and average premiums for a ZIP code.

    This is what turns a zone letter into money: how often this ZIP has actually
    flooded, what was paid out, and what policyholders there actually pay.
    """
    zip_code = str(zip_code).strip()
    if not (len(zip_code) == 5 and zip_code.isdigit()):
        raise ValueError(f"Expected a five-digit ZIP code, got {zip_code!r}")

    claims_url = f"{OPENFEMA_BASE}/FimaNfipClaims"
    params = {
        "$filter": f"reportedZipCode eq '{zip_code}'",
        "$select": "yearOfLoss,amountPaidOnBuildingClaim,amountPaidOnContentsClaim",
        "$top": str(NFIP_CLAIM_PAGE_SIZE),
        "$orderby": "yearOfLoss desc",
        "$inlinecount": "allpages",
    }
    payload = _get(claims_url, params, client=client).json()

    if not isinstance(payload, dict):
        raise MarketDataSchemaError("OpenFEMA claims response was not an object")
    records = payload.get("FimaNfipClaims")
    if records is None:
        raise MarketDataSchemaError(
            "OpenFEMA response has no 'FimaNfipClaims' key; the dataset name may have changed"
        )

    total_count = int(((payload.get("metadata") or {}).get("count")) or len(records))
    total_paid = 0.0
    most_recent = None
    for record in records:
        building = _number(record.get("amountPaidOnBuildingClaim")) or 0.0
        contents = _number(record.get("amountPaidOnContentsClaim")) or 0.0
        total_paid += building + contents
        year = record.get("yearOfLoss")
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None
        if year and (most_recent is None or year > most_recent):
            most_recent = year

    truncated = total_count > len(records)
    caveats = [
        "NFIP claims cover insured losses only; uninsured flood damage is invisible here.",
        "Claims are reported by the policyholder's ZIP, which may differ from the parcel's.",
    ]
    if truncated:
        caveats.append(
            f"Only the {len(records)} most recent of {total_count} claims were summed; "
            "totals understate the full history."
        )

    average_premium, policy_count = None, None
    try:
        average_premium, policy_count = _fetch_average_premium(zip_code, client=client)
    except MarketDataError as exc:
        caveats.append(f"Average premium unavailable: {exc}")

    return FloodLossHistory(
        zip_code=zip_code,
        claim_count=total_count,
        claims_sampled=len(records),
        total_paid=total_paid,
        average_paid=(total_paid / len(records)) if records else None,
        most_recent_loss_year=most_recent,
        average_annual_premium=average_premium,
        policy_count=policy_count,
        truncated=truncated,
        retrieved_at=_now().isoformat(),
        caveats=caveats,
    )


def _fetch_average_premium(
    zip_code: str, *, client: httpx.Client | None = None
) -> tuple[float | None, int | None]:
    """Average NFIP annual premium actually paid in a ZIP."""
    params = {
        "$filter": f"propertyState ne '' and reportedZipCode eq '{zip_code}'",
        "$select": "totalInsurancePremiumOfThePolicy",
        "$top": str(NFIP_CLAIM_PAGE_SIZE),
        "$inlinecount": "allpages",
    }
    payload = _get(f"{OPENFEMA_BASE}/FimaNfipPolicies", params, client=client).json()
    records = (payload or {}).get("FimaNfipPolicies")
    if records is None:
        raise MarketDataSchemaError("OpenFEMA policies response has no 'FimaNfipPolicies' key")

    premiums = [
        value
        for value in (_number(row.get("totalInsurancePremiumOfThePolicy")) for row in records)
        if value and value > 0
    ]
    if not premiums:
        return None, int(((payload.get("metadata") or {}).get("count")) or len(records)) or None
    total_count = int(((payload.get("metadata") or {}).get("count")) or len(records))
    return sum(premiums) / len(premiums), total_count


# --- Underwriting impact --------------------------------------------------


def assess_flood_risk(
    zone: FloodZone,
    *,
    arv: float | None = None,
    loss_history: FloodLossHistory | None = None,
) -> dict:
    """Translate a flood zone into its effect on the deal.

    The value impact is the present value of the recurring insurance premium at
    a documented capitalisation rate. When the premium comes from OpenFEMA it is
    a real figure for that ZIP; otherwise it is an order-of-magnitude estimate,
    and ``premium_measured`` says which.
    """
    premium_measured = bool(loss_history and loss_history.average_annual_premium)
    if premium_measured:
        annual_premium = float(loss_history.average_annual_premium)
        premium_basis = (
            f"OpenFEMA average of NFIP policies in ZIP {loss_history.zip_code}"
        )
    else:
        annual_premium = ESTIMATED_ANNUAL_PREMIUM.get(zone.risk_class, 0.0)
        premium_basis = "Order-of-magnitude estimate by risk class — not measured"

    # Only the portion of the market that actually carries coverage prices it in.
    take_up = INSURANCE_TAKE_UP.get(zone.risk_class, 0.0)
    capitalized = (
        (annual_premium * take_up) / INSURANCE_CAPITALIZATION_RATE
        if INSURANCE_CAPITALIZATION_RATE
        else 0.0
    )
    capped = False
    if arv and arv > 0:
        ceiling = arv * MAX_VALUE_IMPACT_SHARE
        if capitalized > ceiling:
            capitalized, capped = ceiling, True

    warnings: list[str] = []
    verification: list[str] = []

    if zone.in_sfha:
        warnings.append(
            f"Property is in FEMA Special Flood Hazard Area {zone.zone}. Flood insurance is "
            "mandatory for federally-backed financing, which narrows the retail buyer pool."
        )
        verification.extend(
            [
                "Obtain an elevation certificate — it materially changes the premium.",
                "Get a written flood insurance quote before agreeing a contract price.",
                "Confirm state and local flood disclosure obligations to the buyer.",
            ]
        )
    if zone.risk_class == "coastal_high_hazard":
        warnings.append(
            "Coastal high-hazard (V) zone: highest premiums, strictest construction "
            "requirements, and the slowest resale of any flood classification."
        )
    if zone.risk_class == "undetermined":
        warnings.append(
            "FEMA has not determined a flood hazard here. Unmapped is not low-risk; "
            "price the uncertainty or verify independently."
        )
    if zone.base_flood_elevation is not None:
        verification.append(
            f"Compare the structure's lowest floor against the base flood elevation of "
            f"{zone.base_flood_elevation} ft."
        )

    if loss_history:
        if loss_history.claim_count > 0:
            warnings.append(
                f"ZIP {loss_history.zip_code} has {loss_history.claim_count:,} recorded NFIP "
                f"claim(s); most recent loss year {loss_history.most_recent_loss_year}."
            )
        if loss_history.claim_count == 0 and zone.in_sfha:
            warnings.append(
                "No NFIP claims recorded for this ZIP despite SFHA designation — check "
                "whether coverage take-up is simply low."
            )

    return {
        "risk_class": zone.risk_class,
        "in_sfha": zone.in_sfha,
        "mandatory_insurance": zone.mandatory_insurance,
        "estimated_annual_premium": round(annual_premium, 2),
        "premium_measured": premium_measured,
        "premium_basis": premium_basis,
        "insurance_take_up": take_up,
        "capitalized_value_impact": round(capitalized, 2),
        "capitalization_rate": INSURANCE_CAPITALIZATION_RATE,
        "value_impact_capped": capped,
        "value_impact_share_of_arv": (
            round(capitalized / arv, 4) if arv and arv > 0 else None
        ),
        "warnings": warnings,
        "verification_required": verification,
        "method": (
            "Value impact is the present value of the recurring flood insurance premium, "
            f"scaled by the {take_up:.0%} share of buyers expected to carry coverage in this "
            f"risk class and capitalised at {INSURANCE_CAPITALIZATION_RATE:.0%}. It models how "
            "a retail buyer prices a permanent carrying cost; it is not a FEMA or appraisal "
            "figure."
        ),
    }


def source_registry() -> list[dict]:
    """The free FEMA sources this module uses, for the console and audit trail."""
    return [
        {
            "id": "fema_nfhl",
            "name": "FEMA National Flood Hazard Layer",
            "url": FEMA_NFHL_URL,
            "cost": "free",
            "api_key_required": False,
            "api_key_configured": False,
            "licence": "U.S. Government work, public domain",
            "provides": [
                "flood zone by coordinate",
                "special flood hazard area status",
                "base flood elevation",
            ],
            "does_not_provide": ["individual sales", "elevation certificate", "insurance quote"],
            "geography": "parcel-level polygon",
        },
        {
            "id": "openfema_nfip",
            "name": "OpenFEMA — NFIP claims and policies",
            "url": OPENFEMA_BASE,
            "cost": "free",
            "api_key_required": False,
            "api_key_configured": False,
            "licence": "U.S. Government work, public domain",
            "provides": [
                "realized flood claim counts and amounts paid",
                "average NFIP annual premium actually paid",
            ],
            "does_not_provide": ["individual sales", "uninsured flood losses"],
            "geography": "ZIP code",
        },
        {
            "id": "census_geocoder",
            "name": "U.S. Census Bureau Geocoder",
            "url": CENSUS_GEOCODER_URL,
            "cost": "free",
            "api_key_required": False,
            "api_key_configured": False,
            "licence": "U.S. Government work, public domain",
            "provides": ["address to coordinate", "matched address"],
            "does_not_provide": ["individual sales", "ownership"],
            "geography": "point",
        },
    ]

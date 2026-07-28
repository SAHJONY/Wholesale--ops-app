# Free Public Data Sources

What this platform can get for free, what it costs to get the rest, and — most
importantly — what free data **cannot** do. Everything here is a U.S. Government
work in the public domain unless noted.

## Wired and live

Market data lives in `backend/app/market_data.py` and flood risk in
`backend/app/flood_risk.py`. None of these sources requires an API key. Verify
them all against live endpoints with:

```bash
cd backend && python scripts/verify_market_data.py
```

### U.S. Census Bureau — American Community Survey 5-Year Estimates

- **Endpoint**: `https://api.census.gov/data/2023/acs/acs5`
- **Key**: not required. A free key raises the daily quota above ~500 calls/IP.
- **Geography**: ZIP Code Tabulation Area (ZCTA)
- **Cost**: free, unlimited, no licence restriction

| Variable | Meaning |
|---|---|
| `B25077_001E` | Median value, owner-occupied housing units |
| `B25064_001E` | Median gross rent |
| `B25003_001E` / `B25003_002E` | Occupied units / owner-occupied units |
| `B25002_001E` / `B25002_003E` | Total units / vacant units |
| `B25035_001E` | Median year structure built |
| `B19013_001E` | Median household income |

Each estimate has a matching margin-of-error variable (`…M`). The connector
fetches and surfaces MOE, because a median of $145,600 ±$12,800 is materially
weaker evidence than ±$1,200, and the ARV plausibility screen widens its
acceptance band accordingly.

**Two traps this connector handles, and you should know about if you extend it:**

1. **Jam values.** Census returns `-666666666` when an estimate cannot be
   published. Parsed naively, that becomes a negative median home value and
   poisons everything downstream. Values at or below `-100000000` are mapped to
   `None`.
2. **ZCTA ≠ ZIP.** ZCTAs approximate USPS delivery areas but do not match them.
   Some ZIP codes — PO-box-only ones especially — have no ZCTA at all and
   legitimately return no data. That is reported as unavailable, not as zero.

### Federal Housing Finance Agency — House Price Index

- **Endpoints**: five-digit ZIP (annual), CBSA and state (quarterly) CSVs
- **Key**: not required
- **Cost**: free, public domain

This replaces what was a hardcoded `DEFAULT_MONTHLY_APPRECIATION = 0.0035`
(≈4.3%/yr) driving every comparable's market-time adjustment. Real appreciation
is nothing like a constant — the same ZIP in the fixture data ran +14.8% in 2021
and +4.1% in 2023, and neighbouring ZIPs diverge by several points in the same
year. On a comparable sold nine months ago, the difference between an assumed
and a measured rate is a four-figure swing in adjusted price.

Resolution order is ZIP → metro → state, each a real measurement. Only if all
three fail does it fall back to a constant, and that result is labelled
`measured: false` with the failure reasons attached. The valuation adds a warning
to its output whenever an unmeasured rate was used.

> **FHFA moved its site in 2024.** The dataset URLs are configuration
> (`FHFA_HPI_ZIP5_URL`, `FHFA_HPI_METRO_URL`, `FHFA_HPI_STATE_URL`), and the
> parser locates columns by name rather than position. A changed URL or renamed
> column raises `MarketDataSchemaError` instead of silently reading the wrong
> column as appreciation. If `verify_market_data.py` reports schema drift, point
> the environment variable at the current file.

### FEMA — flood zone, realized losses, and actual premiums

Three endpoints, none requiring a key, wired in `backend/app/flood_risk.py`:

| Source | Endpoint | Gives you |
|---|---|---|
| National Flood Hazard Layer | `hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28` | Flood zone polygon covering a coordinate, SFHA status, base flood elevation |
| Census Geocoder | `geocoding.geo.census.gov/geocoder/locations/onelineaddress` | Address → coordinate, so a lead with only a street address can be screened |
| OpenFEMA NFIP | `www.fema.gov/api/open/v2/FimaNfipClaims` and `FimaNfipPolicies` | Actual paid flood claims, and the **average premium actually paid** in a ZIP |

Flood zone is not metadata — it changes the deal. A property in a Special Flood
Hazard Area requires flood insurance for any federally-backed mortgage, which is
a permanent cost the eventual retail buyer capitalises into what they will pay.
That shrinks both the buyer pool and the price.

**How the value impact is derived.** It is the present value of the recurring
premium, scaled by the share of buyers who actually carry coverage, capitalised
at a documented rate:

```
value_impact = annual_premium × take_up_rate ÷ capitalization_rate
```

| Risk class | Zones | Take-up | Why |
|---|---|---|---|
| `coastal_high_hazard` | V, VE | 100% | Mandatory with federally-backed financing |
| `high` | A, AE, AH, AO, AR, A99 | 100% | Mandatory with federally-backed financing |
| `moderate` | shaded X (0.2% annual chance) | 40% | Optional, commonly carried |
| `undetermined` | D | 50% | Unstudied — price roughly half the exposure |
| `minimal` | unshaded X | 0% | Optional and mostly declined, so the market does not price it |

The take-up scaling is load-bearing: without it, capitalising a premium in a
minimal-risk zone invents a discount that does not exist. With
`FLOOD_INSURANCE_CAP_RATE` at its 0.07 default, an AE-zone
property on a $250,000 ARV models to roughly a 10% impact and a VE zone to
roughly 18% — consistent with published SFHA discount estimates.

Where OpenFEMA publishes an average premium for the ZIP, the derivation rests on
what policyholders there really pay and `premium_measured` is `true`. Otherwise
it falls back to an order-of-magnitude figure by risk class, and says so.

**The impact is reported, not deducted, by default.** If the comparables sit in
the same flood zone as the subject, the discount is already embedded in the
derived ARV, and subtracting it again would double-count. Pass
`apply_flood_adjustment: true` only when you know the comparables are not
zone-matched.

**Two failure modes the connector handles explicitly:**

1. **ArcGIS reports errors inside an HTTP 200 body.** Not checking for the
   `error` key means a service outage silently reads as "no flood hazard here",
   which is the most dangerous possible failure for this data.
2. **A missing zone is not a safe zone.** An unmapped coordinate raises rather
   than returning a benign default, and the API returns `status: degraded`
   rather than an empty flood block.

## The comparable-sales gap — read this before planning around it

**There is no free, national source of arms-length comparable sale prices.**
This is the single most important thing to understand about free data in this
business, and no amount of engineering removes it.

Sale prices originate in county recorder and assessor records. They are not
federated nationally, formats differ by county, and — decisively — roughly a
dozen states are **non-disclosure**, meaning sale prices are not public record at
all:

> Alaska, Idaho, Kansas, Louisiana, Mississippi, Missouri (varies by county),
> Montana, New Mexico, North Dakota, Texas, Utah, Wyoming

Classifications shift and several are partial, so verify per jurisdiction before
committing to a market. Note that this platform already excludes Texas in its
acquisition policy.

Your realistic options, in ascending order of cost:

| Option | Cost | Coverage | Effort |
|---|---|---|---|
| County open-data portals (Socrata / ArcGIS REST) | free | one county at a time, disclosure states only | high — a connector per county |
| County assessor bulk downloads | free–low | varies wildly | high — parsing and scheduling |
| MLS via a licensed broker/IDX feed | membership + fees | strong, local | moderate — licence terms restrict storage and display |
| Commercial aggregators (ATTOM, PropStream, etc.) | subscription | national | low — the repo already has `attom_adapter.py` |

The county-portal route is genuinely viable if you operate in a handful of
markets, and this repo's `public_data_providers.py` framework already anticipates
it with per-jurisdiction feature flags. It does not scale to nationwide coverage
without real ongoing engineering.

**What this means in practice:** `POST /deal-intelligence/underwrite` requires
you to supply comparables. It will not invent them, and `estimate_arv` raises
rather than guessing when none survive screening. Free data makes your
comparables *better adjusted* (measured appreciation) and *sanity-checked*
(Census median), but it does not supply them.

## Free sources worth adding next

Not yet wired. Listed with what each is actually good for, so you can judge
whether it earns its integration cost.

| Source | Endpoint | Key | Gives you |
|---|---|---|---|
| FEMA National Risk Index | `hazards.fema.gov/nri` | none | County/tract multi-hazard risk beyond flood — wildfire, wind, surge |
| BLS Local Area Unemployment | `api.bls.gov` | optional free | County unemployment — a leading indicator for distress volume |
| HUD Aggregated USPS Vacancy | HUD portal | registration | Vacancy at tract level. Strong distress signal, but requires approval — not truly open |
| EPA Envirofacts | `data.epa.gov` | none | Environmental hazards near a parcel |
| OpenStreetMap / Nominatim | `nominatim.openstreetmap.org` | none | Geocoding fallback. **Usage policy caps request rates** — not for bulk |

Highest value for the effort now that flood is wired: **BLS unemployment**
(cheap, feeds the distress-volume forecast), then the **FEMA National Risk
Index** for the non-flood hazards that matter in the Gulf markets — wind and
storm surge in particular.

## Compliance notes

These matter as much as the data itself for this business:

- **Public record ≠ unrestricted use.** Many county portals permit access but
  restrict bulk redistribution or commercial resale. Read the terms per
  jurisdiction; the provider framework records `retention` per source for this
  reason.
- **Public data does not override contact law.** A phone number found in a
  public record does not create consent. TCPA, DNC, and state quiet-hours rules
  apply regardless of how the record was obtained. The platform's compliance
  gates are not optional decoration.
- **Never scrape a source that offers an API or bulk download.** Beyond the
  terms-of-service exposure, scraped data has no provenance, and every number in
  this system carries provenance so an underwriting decision stays auditable.
- **Census and FHFA data are public domain** and may be used commercially
  without attribution — though the connectors record source and vintage anyway,
  because an audit trail is worth more than the attribution requirement.

## Provenance contract

Every value the market-data layer returns carries source, geography level,
vintage, retrieval time, and whether it was cached. Appreciation additionally
carries `measured: true|false`. The rule enforced throughout: **an assumption is
never presented as a measurement.** If you extend this layer, keep that
invariant — it is what makes the underwriting record defensible when a deal is
reviewed after the fact.

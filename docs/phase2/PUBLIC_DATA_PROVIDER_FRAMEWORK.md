# Public Data Provider Framework

## Purpose

This framework adds governed support for official public, open-data, and licensed property intelligence sources without coupling downstream workflows to any one vendor.

## Included sources

### Official and free/public where available

- County Recorder APIs and feeds
- County Tax Assessor APIs and GIS services
- Tax delinquent lists
- Code violations and unsafe-structure feeds
- Probate court feeds
- Public foreclosure, lis pendens, and sheriff-sale feeds
- Building and demolition permits
- Municipal and state open-data portals
- FEMA National Flood Hazard Layer
- US Census and TIGER/Line
- EPA environmental public data
- OpenAddresses

### Feature-flagged and licensed/restricted

- MLS/IDX
- USPS vacancy indicators

No licensed or restricted source is enabled by default.

## Nationwide live foundation

The first active nationwide connector uses U.S. Census Bureau Geocoding Services, MAF/TIGER geography, and 2024 ACS 5-year county statistics.

Routes:

- `GET /public-data/nationwide/status`
- `POST /public-data/nationwide/enrich-address`

Owner console:

- `/owner/nationwide-data`

The nationwide service is read-only. It can normalize a U.S. address, return approximate latitude/longitude, state and county FIPS, census tract/block geography, and aggregate county housing context. It does not prove legal ownership, liens, probate, tax delinquency, property value, structure existence, or seller contact information.

Every live enrichment also returns a Property Truth Report. The report separates verified provider claims from unavailable fields and blocking unknowns, provides field-level source and confidence metadata, and keeps underwriting, outreach, and contract readiness blocked until ownership, title, condition, valuation, and contact consent have appropriate evidence.

## Safety invariants

- All jurisdiction and licensed feeds default disabled.
- Nationwide Census enrichment is read-only and never writes to the database.
- All normalization previews are dry-run only.
- No connector in this framework may perform seller outreach, buyer notification, contract action, or payment action.
- Texas properties are rejected before canonical normalization and nationwide enrichment.
- Every canonical record includes source, observation time, confidence tier, authority tier, and retention policy.
- Human owner review remains mandatory before any downstream external action.
- Missing ownership or distress evidence is reported as missing; it is never inferred or fabricated.

## Provider contract

Each provider declares:

- `id`
- `name`
- `category`
- `tier`
- `access`
- `feature_flag`
- `endpoint_env`
- `capabilities`
- `confidence`
- `retention`
- `license_required`

Runtime status is one of:

- `disabled`
- `enabled_default_endpoint`
- `enabled_missing_endpoint`
- `configured`

## Environment configuration

Jurisdiction-specific sources require both a feature flag and an authorized endpoint/feed URL. Examples:

- `ENABLE_COUNTY_RECORDER=true`
- `COUNTY_RECORDER_BASE_URL=https://...`
- `ENABLE_COUNTY_ASSESSOR=true`
- `COUNTY_ASSESSOR_BASE_URL=https://...`
- `ENABLE_TAX_DELINQUENT=true`
- `TAX_DELINQUENT_FEED_URL=https://...`
- `ENABLE_CODE_VIOLATIONS=true`
- `CODE_VIOLATIONS_FEED_URL=https://...`
- `ENABLE_PROBATE_FEEDS=true`
- `PROBATE_FEED_URL=https://...`

Licensed sources additionally require executed rights to access and use the data before enabling:

- `ENABLE_MLS_IDX=true`
- `MLS_IDX_BASE_URL=https://...`
- `ENABLE_USPS_VACANCY=true`
- `USPS_VACANCY_FEED_URL=https://...`

## API routes

- `GET /public-data/catalog`
- `GET /public-data/readiness`
- `POST /public-data/normalize-preview`
- `GET /public-data/nationwide/status`
- `POST /public-data/nationwide/enrich-address`

The preview and nationwide enrichment endpoints do not write to the database.

## Owner interfaces

- `/owner/public-data`
- `/owner/nationwide-data`

The provider page exposes coverage, feature flags, endpoint requirements, confidence, licensing, and retention policy. The nationwide page runs read-only live address enrichment against official Census services.

## Jurisdiction activation boundary

There is no single authoritative free nationwide API for county ownership, deeds, liens, probate, tax delinquency, code violations, or permits. Those records activate county by county only after an official endpoint, permitted use, retention requirements, refresh policy, and field mapping are verified.

## Activation sequence

1. Merge and deploy the common framework.
2. Validate nationwide Census status and one-address enrichment.
3. Register official county endpoints with documented terms.
4. Implement each jurisdiction connector in a separate reviewed release.
5. Run dry-run ingestion and provenance validation.
6. Enable controlled database writes only after migration, audit, rollback, and approval tests pass.
7. Enable licensed providers only after authorization evidence is recorded.

## Implementation boundary

This release creates the common provider contract, governance metadata, feature flags, canonical preview, nationwide read-only Census enrichment, readiness reporting, deployment contract coverage, owner interfaces, and tests. It does not scrape websites, bypass access controls, activate licensed feeds, ingest a production batch, or authorize outbound actions.

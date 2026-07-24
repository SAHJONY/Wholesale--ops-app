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

## Safety invariants

- All sources default to disabled.
- All normalization previews are dry-run only.
- No connector in this framework may perform seller outreach, buyer notification, contract action, or payment action.
- Texas properties are rejected before canonical normalization.
- Every canonical record includes source, observation time, confidence tier, authority tier, and retention policy.
- Human owner review remains mandatory before any downstream external action.

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

The preview endpoint does not write to the database.

## Owner interface

- `/owner/public-data`

The page exposes provider coverage, feature flags, endpoint requirements, confidence, licensing, and retention policy.

## Implementation boundary

This release creates the common provider contract, governance metadata, feature flags, canonical preview, readiness reporting, deployment contract coverage, owner interface, and tests. It does not scrape websites, bypass access controls, activate licensed feeds, ingest a production batch, or authorize outbound actions.

Each real jurisdiction or licensed source should be implemented in a separate reviewed connector release with explicit terms-of-use verification, rate limits, retention policy, and test fixtures.

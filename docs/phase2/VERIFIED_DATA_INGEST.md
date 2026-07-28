# Verified Data Ingest

How real public-record data enters the system, and what the system refuses to
write.

## The rule this implements

The provider framework's governing invariant is that missing evidence is
reported as missing and never inferred or fabricated. Every mechanism here
exists to make that hold under pressure: when a provider volunteers extra
fields, when an operator wants a number that no authority publishes, and when
a jurisdiction offers no machine interface.

## Census geography ingest (active)

`POST /verified-ingest/preview` and `POST /verified-ingest/commit` take
`{"property_ids": [...]}`, geocode each stored property against the U.S. Census
Bureau, and write geography facts with full provenance.

- `preview` is a dry run and writes nothing.
- `commit` requires the `manager` role.
- Each fact records source, source reference, confidence, verification status,
  and observation time.
- `GET /verified-ingest/contract` publishes the write boundary without calling
  out. `GET /verified-ingest/facts/{property_id}` reads back what was written.

### What this source may write

Normalized address parts, coordinate, and FIPS/tract/block identifiers. These
are what a Census match actually establishes, so they land as `verified` at
confidence 92 — below 100 because the geocoder interpolates along address
ranges, which is authoritative for jurisdiction and tract but not for a
rooftop.

### What it may never write

`owner_name`, `owner_mailing_address`, `phone`, `email`, `arv`,
`asking_price`, `mortgage_balance`, `lien_status`, `probate_status`,
`tax_delinquency`, `occupancy_status`, `structure_exists`.

The writable set is a fixed allowlist. A provider response containing owner or
contact fields does not get them written, and there is a test asserting exactly
that. County ACS statistics are returned for review but deliberately not stored
as property facts: an aggregate median is not a fact about one parcel, and
storing it as one invites it to be read as a valuation.

## Distress and listing providers

`GET /distress-data/catalog` and `GET /distress-data/readiness` expose the
provider registry and what remains to configure.

### Public records

Tax delinquency, code violations and unsafe structures, probate dockets, lis
pendens, foreclosure and sheriff-sale calendars, and demolition permits. These
are genuine public records published by the authority that creates them,
overwhelmingly through Socrata or ArcGIS FeatureServer APIs.

Each is disabled by default and configured per jurisdiction:

```
DISTRESS_TAX_DELINQUENCY_ENABLED=true
DISTRESS_TAX_DELINQUENCY_ENDPOINT=https://data.<county>.gov/resource/<dataset>.json
```

Probate is capped at `partially_verified`: a docket names a decedent's estate,
not a parcel, so matching a case to a property is an inference until a recorder
document confirms it.

### Collection policy

Connectors use documented machine interfaces only. There is no HTML-scraping
transport, and adding one would contradict the framework's boundary that
connectors never bypass access controls. A jurisdiction that publishes only a
web page is reported unavailable rather than harvested.

### FSBO and MLS are licensed, not public

For-sale-by-owner inventory is **not** a public record. No government body
maintains an authoritative FSBO dataset, and the sites that aggregate it
license their data under terms that forbid automated collection. FSBO is
therefore a licensed slot alongside MLS/IDX:

- disabled by default;
- an endpoint alone does not enable it — `LISTING_LICENSE_ATTESTATION` must
  carry the agreement reference that authorizes the feed;
- facts stay `unverified`, because seller-stated price and status are
  self-reported. No downstream step may promote them.

To use FSBO inventory, obtain a feed you are licensed to consume and point the
slot at it. The system will not collect it for you from sites that prohibit it.

## Network requirements

Ingest calls these hosts. They must be reachable from wherever the backend
runs:

- `geocoding.geo.census.gov`
- `api.census.gov`
- any jurisdiction endpoint configured above

In a restricted environment these must be allowlisted. Both Census hosts are
free and require no API key.

## Operator sequence

1. Load candidate addresses through `/data-intake` (see `leads.csv` for the
   column contract; it ships as headers only, by design).
2. Run `/verified-ingest/preview` and review the resolved facts.
3. Run `/verified-ingest/commit` to persist them with provenance.
4. Configure jurisdiction endpoints and repeat for distress signals.
5. Review canonical records before any outbound action. Owner review remains
   mandatory.

## Nationwide coverage

Coverage is assembled jurisdiction by jurisdiction, because distress records
are created by roughly 3,100 counties and many thousands of municipalities and
no single nationwide distress dataset exists. What is nationwide is discovery.

`POST /distress-discovery/sweep` searches two federated government catalogs --
the Socrata catalog (`api.us.socrata.com`) and ArcGIS Online search -- for
datasets matching each distress category, and returns registry-shaped
candidates. Nothing is enabled by a sweep: every candidate is marked
`unvalidated` and carries a suggested entry whose `field_map` offers only the
fields its category may write.

The loop for adding a county:

1. `POST /distress-discovery/sweep` with the categories and states you want.
2. Fill in `state`, `county`, `address_field` and `field_map` on the candidates
   you keep. See `config/distress-jurisdictions.example.json`.
3. Add them to `DISTRESS_JURISDICTIONS_FILE`.
4. `POST /distress-ingest/validate` for each — a catalog hit is not proof of
   schema, and an endpoint that resolves may still lack the mapped columns.
5. `POST /distress-ingest/preview`, then `/commit`.

Discovery needs `api.us.socrata.com` and `www.arcgis.com` reachable, alongside
the Census hosts.

## Tenancy

The properties table carries no organization column; tenancy lives in
`WorkspaceEntity`. Both ingest paths scope through it, so a workspace can only
enrich and read its own records.

## Every lead must be a real, locatable property

A lead is actionable only when its property matched an authoritative geocoder
and carries a coordinate that resolves on a map. `/lead-verification` enforces
this:

- `GET /lead-verification/status` — verified vs quarantined, with coverage
  percentage and a Google Maps link per verified lead.
- `GET /lead-verification/lead/{id}` — one lead's verification record.
- `POST /lead-verification/assert-actionable` — pre-flight gate; returns 409
  when the lead is not backed by a verified, locatable property.

`assert_lead_is_actionable()` is the function outbound workflows call before
reaching the outside world.

Unverified leads are **quarantined, not deleted** — visible and countable, but
blocked from action until they verify or are dismissed. Silently dropping an
operator's entry loses work; silently acting on an unverified one is what this
gate exists to stop.

Verification means the geocoder matched the address and returned a coordinate.
It deliberately does **not** claim the parcel is owned by anyone in particular,
is worth anything, or has a structure on it — those need their own sources.

Enforcement is on by default. `REQUIRE_VERIFIED_LEADS=false` disables it, and
the status endpoint reports when it has been.

Map links are built from the verified coordinate and need no API key:
`https://www.google.com/maps/search/?api=1&query={lat},{lng}`. The verified
coordinate is also persisted onto `Property.latitude/longitude`, which had
never been populated.

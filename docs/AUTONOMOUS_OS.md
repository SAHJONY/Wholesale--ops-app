# SAHJONY Autonomous Wholesale OS

## Implemented operating loop

1. Schedule verified acquisition-source runs by market.
2. Create leads through API, CSV/import adapters, or Driving for Dollars.
3. Score leads and create deal records automatically.
4. Queue buyer matching for qualified opportunities.
5. Predict buyer response probability and closing speed.
6. Create approval-gated seller offers.
7. Create approval-gated buyer disposition campaigns.
8. Initialize title and closing checklists.
9. Produce an executive operating brief.
10. Run daily orchestration through Vercel Cron.

## Production APIs

- `POST /acquisition/schedule`
- `GET /executive/brief`
- `POST /deals/from-property/{property_id}`
- `GET /deals`
- `POST /deals/{deal_id}/seller-offer`
- `POST /deals/{deal_id}/closing`
- `GET /properties/{property_id}/buyer-appetite`
- `GET /cron/operations`
- Existing lead, buyer, underwriting, Bland webhook, approval, campaign, and autonomous task APIs remain available.

## Safety and approval policy

The system may analyze, prioritize, draft, queue, and recommend autonomously. It may not send binding offers, launch external campaigns, sign agreements, transfer money, or make legal representations without an owner approval record.

## Data integrity

Acquisition source tasks never fabricate property records. When a licensed/public source connector is absent, the run completes with `connector_required`. Real ingestion requires an authorized provider or public data adapter.

## Autonomous property discovery

The durable job system supports `autonomous_property_acquisition`. On each scheduled run, it can pull up to 1,000 JSON records from one operator-configured HTTPS feed. Arbitrary user-supplied feed URLs are not accepted.

Configure:

- `ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION=true`
- `AUTONOMOUS_PROPERTY_FEED_URL=https://authorized-provider.example/feed`
- `AUTONOMOUS_PROPERTY_FEED_SOURCE=county` (or another supported intake source)
- `AUTONOMOUS_PROPERTY_FEED_TOKEN=` when the provider uses bearer authentication

The response must be a JSON array or `{ "records": [...] }`. Discovered records are normalized and deduplicated through the tenant-scoped acquisition intake. New records are created as `property_candidate`, owner and contact fields are suppressed, and the system emits `PropertyCandidateDiscovered`. Human verification is required before lead conversion or outreach.

### Paste and verify addresses

Managers can paste up to 50 addresses at `/owner/acquisition` using either `street, city, ST ZIP` lines or CSV with optional asking price and HTTPS source URL. Sources may be labeled as public data, Facebook Marketplace/Group, FSBO, or another marketplace. `POST /acquisition-intake/paste-addresses` validates the input, rejects duplicates, verifies each location with Census, adds USGS terrain context, and creates review-only property candidates. The application does not log into or scrape marketplaces or private groups. Pasted addresses and asking prices are operator-supplied claims—not proof of listing rights, ownership, value, distress, or contact consent. Licensed comparable sales are required before wholesale valuation.

### Delete leads and research owner candidates

Workspace managers can delete property-candidate leads from `/owner/acquisition`. Deletion removes the lead and property from the active workspace, suppresses seller contact data, cancels queued work, and records an audit activity. Leads attached to an active deal cannot be deleted until the deal is closed or marked dead.

Authorized reverse-address or people-search findings may be recorded as owner-candidate research with a maximum confidence of 40%. They cannot verify legal ownership. Verification still requires corroboration from an official county assessor, recorder, clerk, or tax-collector record. The application does not automate or scrape people-search websites.

## Required production services

- Managed PostgreSQL / Neon via `DATABASE_URL`
- `CRON_SECRET` for scheduled execution
- Bland.ai credentials for outbound voice initiation
- Upstash/QStash for high-volume distributed queues
- Email/SMS provider credentials for campaign delivery
- Property/MLS/public-record provider credentials for automatic acquisition
- Google Maps Platform credentials for mapping and Street View workflows

## Business operating system

The authenticated owner workspace includes `/owner/business` for company-level management beyond individual transactions:

- monthly revenue, closed-contract, marketing, cash, and tax-reserve targets;
- a tenant-scoped manual income and expense ledger;
- net operating cash, tax reserve, marketing utilization, and cash-runway calculations;
- recurring financial, compliance, vendor, and operational obligations with due-date alerts;
- default daily, weekly, acquisition, and contract-to-close operating playbooks.

This ledger is an operating dashboard, not a replacement for bookkeeping, tax, legal, payroll, or licensed accounting systems. Recorded figures should be reconciled against the company bank account and accounting platform.

## Deployment

```bash
cd ~/Wholesale--ops-app
git checkout main
git pull origin main
cd backend
vercel --prod
```

Verify:

```bash
curl https://backend-pi-opal-65.vercel.app/health
curl https://backend-pi-opal-65.vercel.app/executive/brief
curl https://backend-pi-opal-65.vercel.app/deals
```

## Recommended environment variables

- `DATABASE_URL`
- `CRON_SECRET`
- `BLAND_API_KEY`
- `BLAND_WEBHOOK_SECRET`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `ANTHROPIC_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `HUBSPOT_ACCESS_TOKEN`
- `RESEND_API_KEY`

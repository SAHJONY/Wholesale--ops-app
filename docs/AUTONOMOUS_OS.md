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

## Required production services

- Managed PostgreSQL / Neon via `DATABASE_URL`
- `CRON_SECRET` for scheduled execution
- Bland.ai credentials for outbound voice initiation
- Upstash/QStash for high-volume distributed queues
- Email/SMS provider credentials for campaign delivery
- Property/MLS/public-record provider credentials for automatic acquisition
- Google Maps Platform credentials for mapping and Street View workflows

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

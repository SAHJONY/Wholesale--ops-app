# Architecture

## Runtime

- `frontend`: Next.js operations console
- `backend`: FastAPI domain API
- `db`: PostgreSQL system of record
- `Upstash Redis`: live call/lead state and idempotency
- `QStash`: scheduled outreach and retry delivery
- `Bland.ai`: inbound seller, outbound acquisition and buyer disposition calls
- `Claude`: structured analysis, summaries and next-action recommendations (see `DECISION_INTELLIGENCE.md`)

## Safety boundary

The system may research, score, summarize, schedule and draft. A human operator must approve contracts, assignments, payments, mass campaigns and representations about funds or legal status.

## Primary workflow

1. Ingest a seller/property lead.
2. Calculate visual/public-record distress score.
3. Qualify seller by phone.
4. Estimate ARV, repairs and MAO.
5. Approve offer/contract.
6. Rank buyers against the property buy box.
7. Launch sequenced disposition outreach.
8. Capture offers, proof of funds and walkthrough requests.
9. Approve assignment and coordinate closing.
10. Feed outcomes back into buyer and lead scores.

## Decision intelligence

Valuation, scoring, buyer matching, and forecasting run on calibrated models
rather than fixed formulas. See `DECISION_INTELLIGENCE.md` for the engines, their
uncertainty handling, and the API surface.

## Production hardening backlog

- Authentication and organization tenancy
- Alembic migrations
- QStash signature verification and workers
- Upstash state adapter
- Bland.ai call initiation service
- Google Maps JavaScript and Street View UI
- Licensed property-data integrations
- CRM/calendar/e-sign integrations
- TCPA/DNC consent and quiet-hours enforcement
- Tests, observability and deployment pipelines

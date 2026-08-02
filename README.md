# SAHJONY Autonomous Wholesale Workforce

Production-oriented MVP for residential and commercial real-estate wholesale operations.

## Included

- Next.js operations dashboard
- FastAPI REST API
- PostgreSQL data model
- Upstash Redis lead and call state
- Bland.ai inbound/outbound webhook handling
- Distressed single-family lead scoring
- Residential MAO and commercial valuation services
- Predictive cash-buyer matching
- Driving-for-dollars lead intake
- Human approval gates and audit-ready architecture
- Property Truth Reports with field-level provenance, explicit unknowns, and evidence gates

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Frontend: http://localhost:3000

API docs: http://localhost:8000/docs

## Core workflow

Lead intake → distress scoring → seller call → underwriting → approval → buyer matching → disposition → closing.

See `docs/ARCHITECTURE.md` and `fable5-plan.yaml` for the system blueprint.
# BatchData MCP OAuth

Provider Intelligence uses BatchData's MCP server through an owner-authorized OAuth flow. Configure `BATCHDATA_MCP_URL`, `BATCHDATA_OAUTH_CALLBACK_BASE_URL`, and a stable `BATCHDATA_OAUTH_ENCRYPTION_KEY` of at least 32 characters. Run `alembic upgrade head` from `backend/` before deploying the code that introduces the OAuth tables.

The owner connects BatchData from Provider Intelligence. Tokens are encrypted at rest, scoped to the organization, refreshed server-side, and never returned to the browser. Tool verification lists available MCP tools without performing a billable property lookup. Property data remains preview-first and cannot authorize outreach or offers.

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
# BatchData MCP

Provider Intelligence uses BatchData's MCP server with a server-side Bearer token. Configure `BATCHDATA_MCP_URL=https://mcp.batchdata.com` and the sensitive `BATCHDATA_API_TOKEN`. This integration does not require an OAuth callback, encryption key, or database migration. BatchData contact enrichment is a separate REST integration configured with `BATCHDATA_SKIPTRACE_URL` and `BATCHDATA_API_KEY`; its readiness and compliance gates do not represent MCP readiness.

Tool verification lists available MCP tools without performing a billable property lookup. The token is read only by the backend and is never returned to the browser. Property data remains preview-first and cannot authorize outreach or offers.

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

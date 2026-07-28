# SAHJONY Autonomous Wholesale Workforce

Production-oriented MVP for residential and commercial real-estate wholesale operations.

## Included

- Next.js operations dashboard
- FastAPI REST API
- PostgreSQL data model
- Upstash Redis lead and call state
- Bland.ai inbound/outbound webhook handling
- Free public market data (Census ACS, FHFA House Price Index — no API key)
- FEMA flood zone screening with capitalized insurance impact on value
- Comparable-sales ARV valuation with confidence intervals
- Monte Carlo deal underwriting and risk-adjusted offer pricing
- Claude structured-output reasoning with deterministic fallback
- Outcome-calibrated lead scoring that learns from closed deals
- Probabilistic cash-buyer matching and portfolio-level disposition
- Probability-weighted pipeline revenue forecasting
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

See `docs/ARCHITECTURE.md` and `fable5-plan.yaml` for the system blueprint,
`docs/DECISION_INTELLIGENCE.md` for the modelling layer, and
`docs/FREE_DATA_SOURCES.md` for what public data can and cannot supply.

Verify the free data connectors against live endpoints:

```bash
cd backend && python scripts/verify_market_data.py
```

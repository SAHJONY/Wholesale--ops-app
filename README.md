# SAHJONY Wholesale Ops

Operations system for residential real-estate wholesale: find distressed
property from public records, verify it is a real parcel, price it, contact the
owner under the communications rules, match a cash buyer, and close.

Next.js dashboard, FastAPI backend, PostgreSQL, Alembic migrations.

## Status

**The application runs. It is not yet doing business, and the gap is
credentials and network access rather than code.**

Nothing here can produce a lead until a property-data provider is configured
and the public-record hosts are reachable. Both are listed under
[Going live](#going-live) with the exact commands that report on them. Ask the
running system rather than this file — `GET /go-live/snapshot` and
`GET /launch-validation/snapshot` both read one registry
(`app/provider_requirements.py`) and will agree with each other.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Frontend on http://localhost:3000, API docs on http://localhost:8000/docs.

## The loop

```
public records ─▶ verify the parcel is real ─▶ stack distress signals
      ─▶ value it ─▶ contact the owner (compliance gate) ─▶ match a cash buyer
      ─▶ contract, title, assignment
```

Everything else in the repository exists to serve that sequence or to prove a
step actually happened.

## What the system will not do

These are enforced by code and by tests that fail when the guard is removed,
not by convention:

- **No unverified lead is actionable.** A property that cannot be resolved to a
  real, locatable address does not reach outreach.
- **Absence of evidence is never reported as evidence.** A property with no
  distress records reads as "nothing pulled", never as "nothing wrong".
- **Texas is excluded** from the wholesale workflow, before normalization.
- **No outbound message without owner approval**, and none outside quiet hours,
  past the frequency cap, to a suppressed contact, or without AI disclosure on
  an automated call.
- **Recording requires consent** in all-party states.
- **Connectors read published interfaces.** Nothing scrapes, and nothing works
  around an access control.

Run `python backend/scripts/audit_guard_coverage.py` to check these. It does not
read the guards, it breaks each one, runs its tests, and reports any that the
suite failed to notice.

## Going live

### 1. Database

Set `PRODUCTION_DATABASE_URL` in GitHub Actions secrets, then merge to `main`.
The deploy workflow runs `alembic upgrade head` before deploying the code that
depends on it. Without it, migrations never run and tables are reported missing.

### 2. Property data — the one that unblocks everything

Either provider satisfies it:

- `ATTOM_API_KEY`, or
- `SMARTY_AUTH_ID` **and** `SMARTY_AUTH_TOKEN` together — a *secret key* pair
  from the Secret keys tab. The embedded key on the same page is browser-scoped
  and is rejected when the request comes from a cloud host, which is where this
  backend runs.

### 3. Outbound network access

The verified-lead path needs these hosts. None require an API key:

| Host | Why |
|---|---|
| `geocoding.geo.census.gov` | **Required.** Resolves an address to a real place. Without it no lead verifies. |
| `api.census.gov` | County demographics used in market scoring |
| `api.us.socrata.com` | Discovers county open-data portals carrying distress records |
| `www.arcgis.com` | The other county transport, for FeatureServer datasets |

```bash
cd backend && python scripts/preflight_data_access.py
```

That reports which are reachable and states plainly that no lead can be
verified while the required one is blocked.

### 4. Everything else

Optional in the sense that the loop runs without them, each closing off one
stage. `GET /go-live/snapshot` names the exact variables still missing:

| Capability | Needs |
|---|---|
| Seller calls and texts | `TWILIO_ACCOUNT_SID` **and** `TWILIO_AUTH_TOKEN`, or `BLAND_AI_API_KEY` |
| Owner contact details | `BATCHDATA_API_KEY` **and** `BATCHDATA_SKIPTRACE_URL` |
| Property detail lookups | `BATCHDATA_MCP_URL` **and** `BATCHDATA_API_TOKEN` |
| Contracts | `DOCUSEAL_URL` **and** `DOCUSEAL_API_KEY` |
| Email | `SMTP_USER` **and** `SMTP_PASS`, or `RESEND_API_KEY` |
| Document storage | `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` |
| Model-backed analysis | `ANTHROPIC_API_KEY`, falling back to `OPENAI_API_KEY` |

Where two variables are joined by **and**, one alone counts as unconfigured
rather than half-working — a credential that is set but unusable is worse than
one that is missing, because the checklist looks answered.

Analysis degrades to deterministic rules without a model key. That is a working
degradation, not a failure.

### 5. Deployment protection

The backend Vercel project must have Vercel Authentication set to **Only
Preview Deployments**. Set to "All deployments" it also walls off production,
and the deploy workflow's health check fails against the SSO page rather than
the API.

## Verifying

```bash
cd backend
python -m pytest -q                       # full suite
python scripts/audit_guard_coverage.py    # break each guard, check tests notice
python scripts/release_gate.py            # routes, migrations, required tables
python scripts/preflight_data_access.py   # can a lead be verified at all
```

## Documentation

| | |
|---|---|
| `docs/ARCHITECTURE.md` | System blueprint |
| `docs/DECISION_INTELLIGENCE.md` | The reasoning layer and its fallback chain |
| `docs/FREE_DATA_SOURCES.md` | What public data can and cannot supply |
| `docs/BLAND_VOICE_SETUP.md` | Voice configuration, webhook signing |
| `docs/DEPLOY_VERCEL_BACKEND.md` | Backend deployment |
| `docs/research/` | Source material for scoring vocabularies |

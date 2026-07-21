# Production hardening report

Date: 2026-07-21

## Result

The application now uses Alembic as the only runtime schema authority. Revision
`20260721_0004` creates every application table missing from the earlier revisions
and safely skips tables created by legacy startup behavior. `SCHEMA_MODE=strict` is
the default, and runtime imports no longer issue schema DDL.

All Python `datetime.utcnow()` calls were replaced with timezone-aware UTC values.
The root npm lockfile is the single workspace lockfile used by CI. A read-only
production smoke runner checks the API health/OpenAPI contract and all 28 owner pages.

## Verified locally

- Backend: 50 tests passing.
- Fresh database: Alembic upgrade through `20260721_0004` passing.
- Migration guard and release gate: passing on a fresh migrated database.
- Owner surface: 28 page modules present and included in the production build check.
- API surface: OpenAPI generation and critical route registration covered by tests.

## Migration checklist

- Back up the production Neon database and record the restore point.
- Extract the raw URI with `python scripts/extract_neon_uri.py | pbcopy`.
- Set `DATABASE_URL` and confirm `python backend/scripts/migration_guard.py --json` reports the expected pre-migration state.
- Run `cd backend && alembic upgrade 20260721_0004` exactly once per environment.
- Confirm `python scripts/migration_guard.py --json` reports `state: current`.
- Run `python scripts/release_gate.py` and retain its JSON output as release evidence.
- Do not use `Base.metadata.create_all`, `alembic stamp`, or manual DDL for normal deployments.

## Deployment checklist

- Configure production secrets in the hosting providers; never commit connection strings.
- Set `SCHEMA_MODE=strict`, `DATABASE_URL`, `APP_URL`, `BACKEND_URL`, and `NEXT_PUBLIC_API_URL`.
- Run backend tests and the root frontend production build.
- Apply and verify Alembic migrations before shifting traffic.
- Deploy backend, then frontend.
- Run `python scripts/production_smoke.py --frontend-url <url> --api-url <url>`.
- Verify provider credentials and webhook signatures for ATTOM, BatchData, DocuSeal, and Twilio/Bland AI.
- Exercise one supervised end-to-end deal with production-safe test data.
- Review logs, error rates, database connections, and rollback readiness before go-live.

## Remaining external validation

Live provider integrations, Neon migration execution, hosted owner-page responses, and
real-data end-to-end workflows require production credentials and deployed URLs. They
must be completed during the release window; local checks cannot certify those systems.

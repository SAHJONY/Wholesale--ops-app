# SAHJONY gstack integration

This repository uses the `skills/sahjony-*` family as the engineering operating system for Wholesale OS.

## Risk routing
- New provider/integration: engineering + CSO + review + QA + release.
- Auth/tenant changes: engineering + CSO + review + QA + release + canary.
- Outbound SMS/voice: CEO + engineering + CSO + review + QA + release + canary.
- Underwriting/revenue: CEO + engineering + review + QA.
- Pure UI copy/style: design review + lightweight QA.

## Required invariants
1. Every tenant-owned entity access proves organization ownership.
2. External communications remain behind deterministic compliance plus explicit authorization.
3. Frontend API routes/payloads match the authenticated backend contract.
4. Realized revenue is recognized from explicit non-duplicated events.
5. Provider readiness reflects capabilities implemented in code.
6. Production revisions are observable and rollbackable.

## CI gates to maintain
- Python tests.
- Frontend build/typecheck.
- Alembic single-head check.
- Guard-coverage audit.
- Tenant-isolation regression suite.
- Frontend/backend contract test.
- Release gate.

No skill grants itself merge, deployment, provider-credential mutation, outbound messaging, contract execution, or financial authority.

# SAHJONY Wholesale OS — A-to-Z gstack audit

Date: 2026-08-08

## Disposition
Controlled production expansion should remain supervised until the P0/P1 remediation in this branch passes CI and review.

## Findings addressed in this branch

### P0 — Tenant integrity in SMS and attribution
Core Lead IDs are global while organization ownership is represented through `workspace_entities`. New SMS/attribution records now fail closed at the SQLAlchemy model boundary unless the organization owns the referenced lead. This protects the write path even if a future endpoint forgets an application-layer ownership check.

### P1 — Legacy root API contract
The obsolete root client consumed retired global endpoints. `/` now redirects to the authenticated `/owner` workspace, making the current owner application canonical and removing the stale API surface from active use.

### P1 — Campaign timezone contract mismatch
Campaign Manager historically sent `recipient_timezone`, while execution only read `timezone_overrides`. Execution now accepts the explicit batch-level shape for compatibility and still gives per-recipient overrides priority. No timezone is guessed.

### P1 — Revenue double counting
`assignment_closed` and `assignment_fee_received` could both carry the same fee amount. Realized assignment revenue is now recognized only from `assignment_fee_received`; close events remain operational milestones.

## Follow-on architecture work
The side-table tenancy model remains structurally fragile. A future controlled migration should place `organization_id` directly on tenant-owned core entities or force all access through a tenant-aware repository layer. Capability-based authorization should also supplement the current rank-based role helper.

## Strong controls already present
- owner approval remains separate from dispatch;
- fresh compliance is re-evaluated before Bland sends;
- STOP/suppression and quiet-hour controls fail closed;
- Bland webhooks are signed and idempotent;
- appointment parsing and calendar free/busy fail closed;
- AI remains draft/route only for outreach;
- seller-stated facts remain distinct from verified facts;
- deterministic model fallbacks exist;
- provider readiness is tied to implemented adapters;
- deploy revision reporting exists.

## Release gate
Before merge: run targeted tests, full backend regression, frontend build/typecheck, migration single-head check, guard-coverage audit, tenant-isolation tests, and release gate. No production deployment is authorized by this document.

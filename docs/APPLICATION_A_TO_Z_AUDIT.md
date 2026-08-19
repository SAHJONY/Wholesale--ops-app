# SAHJONY Wholesale OS — A-to-Z gstack audit

Date: 2026-08-19

## Disposition
Controlled production expansion remains supervised. The scheduled operating layer is active and producing persisted results, but acquisition quality and provider readiness still require remediation before the system should be treated as fully autonomous production operations.

## Latest Cron Jobs — 2026-08-19

Vercel currently declares three daily cron jobs in `vercel.json`. All three routes require `CRON_SECRET` authorization and fail closed when the secret is missing or invalid.

| Job | Endpoint | Schedule (UTC) | Central time during DST | Latest observed execution | Latest result |
| --- | --- | --- | --- | --- | --- |
| Scheduled autonomous operations | `/api/backend/scheduled/operations` | `0 13 * * *` | 8:00 AM CT | 2026-08-19 13:34:05 UTC | Completed; 9 agents ran, 1 task executed, 1 completed, 0 failed, 1 follow-up created |
| Integration reliability monitor | `/api/backend/integration-reliability/scheduled` | `15 13 * * *` | 8:15 AM CT | 2026-08-19 13:40:06 UTC | Completed; 1 organization checked, 3 providers ready, 15 blocked, 0 new alerts, 0 resolved alerts |
| Durable background jobs | `/api/backend/jobs/scheduled` | `30 13 * * *` | 8:30 AM CT | Latest persisted jobs created 2026-08-19 14:25:21 UTC | `buyer_box_match_refresh` completed with 74 matches; `autonomous_property_acquisition` completed but received 0 records |

### Scheduled autonomous operations
The latest persisted cycle (`crm_activities.id=282`) completed successfully for `SAHJONY Wholesale Operations` with `trigger=vercel_cron`. Nine autonomy agents ran. One queued task executed and completed with zero task failures. One follow-up task was created.

The same cycle ranked 19 workspace markets. None reached high-confidence status because available evidence coverage remained incomplete. The strongest current ZIP-level signals were 77051 and 77084, each with a composite score of 65.6, evidence coverage of 45%, low confidence, and 31 cash buyers in workspace evidence. The principal missing dimensions were buy-box fit, distress supply, and verified coverage.

### Integration reliability monitor
The latest reliability run (`integration_reliability_runs.id=32`) completed successfully at 2026-08-19 13:40:06 UTC. It checked one organization. Three providers were ready and fifteen were blocked. No new reliability alerts were opened and none were resolved during that run.

This means the monitor itself is functioning, but most provider integrations are still not production-ready. Provider readiness remains a material operating constraint.

### Durable background jobs
The latest buyer-box refresh (`background_jobs.id=3`) completed on its first attempt with no error. It produced 74 buyer matches, zero fast-track matches, and zero POF-verified buyer matches. The active policy is `continuous_general_acquisition_plus_buyer_box_fast_lane`.

The latest autonomous property-acquisition job (`background_jobs.id=2`) also completed on its first attempt, but produced no acquisition inventory: received 0, created 0, updated 0, duplicate 0, rejected 0. It remained review-only. The run attempted public-source collection across Oklahoma, Oregon, Pennsylvania, Rhode Island, and South Carolina and recorded HTTP errors for every tested collector family: tax distress, code/vacancy, foreclosure/public sale, probate/estate, FSBO public, and public Facebook-group FSBO. Coverage score was therefore 0.

Operational interpretation: the job scheduler and worker lifecycle are functioning; the principal failure is upstream public-source acquisition, not queue execution.

## Cron operating assessment

- Cron routing is present and persisted executions prove the scheduled layer is running.
- Autonomous operations are successfully creating and completing supervised work.
- Buyer-box matching is operational and produced 74 matches in the latest durable job.
- No current POF-verified buyer matches were produced, so cash-buyer readiness must not be overstated.
- Integration reliability remains weak: 3 ready versus 15 blocked providers in the latest run.
- Autonomous acquisition is technically executing but is not yet productive because the tested public collectors returned HTTP failures and no candidate records.
- Vercel schedule timestamps are nominal trigger times; observed persisted execution can occur later than the declared minute and should be evaluated from database execution timestamps rather than assumed exact firing time.
- SMS-related background capability remains approval-only/no-dispatch under the current operating policy. Phone remains the active outreach channel.

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

Cron-specific follow-on work:
- repair or replace the failing public-source collectors used by `autonomous_property_acquisition`;
- raise provider readiness beyond the current 3/18 ready state;
- add explicit cron execution telemetry that records scheduled time, start time, completion time, latency, HTTP result and deployment revision;
- distinguish cron-triggered background jobs from manually enqueued jobs in persisted job metadata;
- keep acquisition and buyer evidence fail-closed when source authority, ownership, POF or property facts are not verified.

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
- deploy revision reporting exists;
- cron endpoints require `CRON_SECRET` and fail closed;
- durable jobs recover stale locks, retry with backoff, and move exhausted jobs to dead letter.

## Release gate
Before any claim of full autonomous production readiness: run targeted tests, full backend regression, frontend build/typecheck, migration single-head check, guard-coverage audit, tenant-isolation tests, cron execution validation, provider readiness validation, public-source acquisition verification, and release gate. Scheduled execution alone is not evidence that upstream data acquisition or provider integrations are healthy.

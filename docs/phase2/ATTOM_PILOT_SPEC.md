# ATTOM Production Pilot Specification

Version: 1.0

Status: Proposed implementation contract

Owner: SAHJONY Wholesale Operations

Last updated: 2026-07-21

## 1. Objective

Execute one fully supervised wholesale transaction using ATTOM as the only
production acquisition provider. The pilot must ensure that every decision is
explainable, every action is auditable, every external operation requires explicit
human authorization, and every failure is recoverable.

The pilot is limited to one non-Texas county and 25–50 properties. ATTOM access is
read-only. External communications, contract actions, and buyer notifications are
disabled by default and remain subject to the safety contract in section 4.

## 2. Entry criteria and required decisions

Implementation may start only after these items are recorded in an approved pilot
configuration or change record:

- Pilot county and state.
- ATTOM products and production API access.
- Daily request, quota, and spending limits.
- Minimum record confidence threshold.
- Duplicate matching policy and thresholds.
- Raw provider payload retention period.
- Named owner approver and backup approver.
- Approval lifetime and escalation window.
- MAO and assignment-margin parameters.
- Validation-failure halt threshold.
- Dry-run enforcement owner.

Credentials must be stored in the deployment secret manager. They must never be
committed, logged, embedded in audit payloads, or supplied to client-side code.

## 3. Pilot architecture

```text
ATTOM API
    |
    v
Provider Health Monitor
    |
    v
Rate Limiter + Retry Queue
    |
    v
Canonical Property Model
    |
    v
Deduplication Engine
    |
    v
Compliance Filters
    |
    v
Explainable Intelligence Pipeline
    |
    v
Owner Review Queue
    |
    v
Approval-Gated Acquisition Workflow
```

Provider-specific representations stop at the adapter boundary. Downstream
components consume only canonical records, provenance, validation results, and
processing events.

## 4. Platform safety contract

### 4.1 Invariant

No outbound communication, contract action, buyer notification, or equivalent
external side effect may execute unless all of the following are true at the point
of execution:

```text
DryRun is false
AND approval is valid
AND approval is not expired
AND approval is unused
AND approval.action_hash equals requested_action_hash
AND approval.workspace_id equals request.workspace_id
AND approval.action_type equals request.action_type
```

Otherwise, the action must be rejected and the rejection must be recorded.

### 4.2 Enforcement boundaries

Requirement `SAFE-001` must be enforced independently in:

- The API authorization boundary.
- The service that owns the external side effect.
- Background workers and queue consumers.
- Manual retry and replay endpoints.
- Scheduled jobs.
- Database constraints or atomic consumption logic where applicable.

The UI may explain and initiate approvals, but client-side state is never sufficient
authorization. Provider adapters must not expose a bypass path around the owning
service. Failures must be closed by default.

### 4.3 Approval object

Each approval records:

- Approval ID and action ID.
- Workspace ID and property ID.
- Approving user ID.
- Action type and canonical action payload hash.
- Issued and expiration timestamps in UTC.
- Approval hash and signing/version metadata.
- Consumption timestamp and consuming execution ID.
- Decision reason.

Approvals are single-use, action-specific, workspace-scoped, time-limited, and
consumed atomically with dispatch. Payload changes invalidate the approval.

### 4.4 Blocked-action evidence

Every rejected attempt records `SAFE-002` evidence:

- Reason code.
- Requester and workspace.
- UTC timestamp and correlation ID.
- Action type and requested action hash.
- Approval state.
- Dry-run state.
- Originating API, worker, retry, or scheduled-job identity.

Audit evidence must not contain credentials or unnecessarily sensitive provider data.

## 5. Release Gate 1 — Provider foundation

### 5.1 Requirements

| ID | Requirement |
| --- | --- |
| `ATTOM-001` | Authenticate through server-side production credentials and validate configuration without exposing secrets. |
| `ATTOM-002` | Enforce connect and read timeouts. |
| `ATTOM-003` | Track rate limits and quota before and after requests when ATTOM exposes them. |
| `ATTOM-004` | Retry eligible failures with bounded exponential backoff and jitter; never retry permanent failures blindly. |
| `ATTOM-005` | Open a circuit breaker after the configured failure threshold and support controlled recovery. |
| `ATTOM-006` | Attach workspace-scoped correlation and provider request IDs. |
| `ATTOM-007` | Classify authentication, quota, rate-limit, timeout, transport, provider, validation, and internal errors. |
| `ATTOM-008` | Emit provider request telemetry without credentials or prohibited payload data. |
| `ATTOM-009` | Expose `GET /provider/attom/status` through an appropriately protected operational endpoint. |

### 5.2 Telemetry contract

Each provider operation captures:

- Provider and endpoint identifier.
- Provider request ID and internal correlation ID.
- Workspace ID.
- UTC start and completion timestamps.
- Latency in milliseconds.
- HTTP status when available.
- Quota before and after the request.
- Retry count.
- Normalized error type.

The health response includes status, quota remaining, recent latency, recent error
rate, and circuit state. It must represent unavailable metrics as unknown rather than
inventing values.

### 5.3 Exit criteria

- `G1-E1`: Production authentication verified.
- `G1-E2`: Health endpoint operational and protected as designed.
- `G1-E3`: Timeout, retry, jitter, and circuit-breaker tests pass.
- `G1-E4`: Quota and usage telemetry validated against provider observations.
- `G1-E5`: Secret-scanning and sanitized-error tests show no credential leakage.

## 6. Release Gate 2 — Data governance

### 6.1 Canonical property

`CanonicalProperty` owns the internal property ID, normalized address, coordinates,
owner evidence, parcel identifiers, equity evidence, distress indicators, tax data,
and canonical lifecycle state. Provider-specific fields remain in a versioned raw or
adapter-owned representation and cannot become implicit downstream dependencies.

### 6.2 Field provenance

Every imported field or evidence item records `DATA-001` provenance:

- Provider.
- Provider record ID.
- Observed and retrieved timestamps in UTC.
- Transformation name and version.
- Confidence.
- Source reference or raw-record reference permitted by retention policy.

Provenance is append-only. A new observation may supersede an old value in the
canonical projection but may not erase its history.

### 6.3 Validation and rejection

Every candidate passes deterministic checks for:

- Address normalization and required address components.
- Parcel identifier syntax and consistency when present.
- Duplicate identity and match confidence.
- Configured minimum confidence.
- Texas exclusion.
- Required-field completeness.
- Coordinate/address consistency when geocoding evidence exists.

Rejected records remain auditable and include structured reason codes. Reprocessing
creates new events; it does not rewrite the original decision.

### 6.4 Immutable processing history

At minimum, the event ledger supports:

```text
INGESTED
VALIDATED
REJECTED
ENRICHED
SCORED
READY_FOR_REVIEW
APPROVED
ON_HOLD
EXPIRED
```

Events contain identity, workspace, actor, correlation, UTC occurrence time, schema
version, transition reason, and references to relevant evidence. Events are never
updated in place or deleted by normal application workflows.

### 6.5 Exit criteria

- `G2-E1`: Repeated validation of identical inputs produces identical outcomes.
- `G2-E2`: Duplicate policy passes exact, normalized, ambiguous, and cross-workspace tests.
- `G2-E3`: Provenance completeness is 100% for accepted records.
- `G2-E4`: Texas exclusion cannot be bypassed by formatting variations.
- `G2-E5`: Audit immutability is verified at service and database boundaries.

## 7. Release Gate 3 — Controlled operations

### 7.1 Explainable intelligence

The pipeline computes distress, equity, buyer demand, data confidence, and acquisition
priority. Every score returns contributing factors, input evidence references,
calculation version, missing-data warnings, and confidence. Seller motivation may use
only lawful and documented signals.

### 7.2 Owner review queue

Allowed states are:

```text
NEW
READY_FOR_REVIEW
APPROVED
REJECTED
ON_HOLD
EXPIRED
```

Each decision records the approver, decision, reason, issued timestamp, expiration,
and reviewed evidence version. Review actions are Approve, Reject, Hold, and Request
Additional Review. Approval of a candidate does not implicitly approve outreach,
contracting, buyer notification, or another external action.

### 7.3 Dry-run mode

Dry-run is enabled by default for the pilot. While enabled, the platform may calculate,
render, queue simulations, and record expected effects, but must block emails, SMS,
calls, contract execution, buyer notifications, and any other external side effect.

### 7.4 Exit criteria

- `G3-E1`: Unauthorized outbound actions equal zero.
- `G3-E2`: Approval coverage for attempted external actions is 100%.
- `G3-E3`: Expired, reused, cross-workspace, wrong-type, and wrong-hash approvals are rejected.
- `G3-E4`: API, worker, queue, retry, and scheduled-job bypass tests pass.
- `G3-E5`: Blocked actions produce complete audit evidence.
- `G3-E6`: Dry-run enforcement is verified for every external channel.

Any failure of `SAFE-001` is an unconditional release blocker.

## 8. Release Gate 4 — Pilot execution

### 8.1 Rehearsal 1: synthetic

Verify ingestion, validation, deduplication, scoring, approvals, blocked actions, audit
evidence, and rollback using synthetic records.

### 8.2 Rehearsal 2: ATTOM read-only

Process 25–50 real ATTOM properties from the approved county. External actions remain
disabled. Reconcile provider telemetry, provenance, validation, and cost observations.

### 8.3 Rehearsal 3: production workflow simulation

Run production components with seller communication, buyer communication, and contract
execution blocked. Verify action-specific approvals and operational halt behavior.

### 8.4 Supervised transaction

Process one real transaction through lead review, offer approval, contract approval,
buyer matching, disposition approval, assignment, closing, and revenue recording.
Every external step requires a fresh approval for the exact action.

### 8.5 Exit criteria

| Requirement | Target |
| --- | --- |
| Provider availability during pilot | At least 99% |
| Duplicate rate | Less than 2% |
| Validation accuracy | At least 95% |
| Complete provenance | 100% |
| Unauthorized outbound actions | 0 |
| Human approval coverage | 100% |
| Audit completeness | 100% |
| Rollback exercise | Successful |
| Dry-run rehearsals | At least 3 |
| Supervised transactions | 1 successful completion |

## 9. Operational KPIs

Provider KPIs are availability, latency, quota utilization, request success, retry and
timeout rates, circuit events, and cost per property. Data-quality KPIs are validation
pass rate, duplicate rate, incomplete-record rate, provenance completeness, and
confidence distribution.

Acquisition KPIs are review volume, approval rate, approval latency, valuation latency,
time to offer, contract rate, and explainability coverage. Disposition KPIs are buyer
match precision, assignment margin, and time to assignment. System KPIs are API uptime,
queue age and depth, job success, retry rate, audit consistency, and rollback readiness.

Metric definitions, windows, exclusions, and data sources must be versioned before the
pilot begins. Unknown data must not be treated as a successful measurement.

## 10. Automatic halt and rollback

The pilot enters a halted state when any of these occurs:

- Provider authentication failure.
- Quota exhaustion or configured spend limit reached.
- Validation failures exceed the configured threshold.
- Any unauthorized outbound attempt.
- Audit-log inconsistency.
- Approval verification failure.
- Critical deployment or schema regression.

The halt procedure must:

1. Disable provider ingestion.
2. Pause pilot background queues and scheduled dispatch.
3. Force server-side dry-run mode.
4. Preserve provider evidence, processing history, approval records, and audit events.
5. Generate an incident report with correlation identifiers and timeline.
6. Require explicit owner approval before resuming.

Rollback must be rehearsed without deleting audit evidence. Database rollback uses a
forward-fix or explicitly reviewed Alembic downgrade only when the revision declares it
safe. Deployment rollback must retain the incident release identifiers.

## 11. Traceability and release evidence

Every Phase 2A pull request must cite one or more requirement IDs from this document.
Tests should use the same IDs in names, markers, or docstrings where practical.

Each release-gate evidence bundle must include:

- Commit and deployment identifiers.
- Migration head and database revision.
- Requirement-to-test mapping.
- Automated test and smoke results.
- Provider-health and quota evidence with secrets removed.
- Approval coverage and blocked-action report.
- Audit-integrity result.
- Known exceptions, owner, expiration, and remediation.
- Rollback readiness or rehearsal result.

No gate may be marked complete from a verbal assertion alone.

## 12. Change control

Changes to the safety invariant, approval semantics, dry-run behavior, pilot geography,
provider scope, exit thresholds, or halt conditions require owner approval and a
versioned update to this document before implementation. A change that weakens a safety
control requires an explicit risk record and may not be bundled into an unrelated
feature release.

Phase 2B providers and additional counties remain out of scope until all Gate 4 exit
criteria are evidenced and approved.

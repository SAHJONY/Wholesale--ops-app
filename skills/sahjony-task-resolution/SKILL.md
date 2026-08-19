# SAHJONY Task Resolution Skill

## Purpose
Resolve blocked, pending, or partially completed Wholesale OS tasks by routing them to the safest available execution path and requiring proof before marking success.

## Core Rule
Never manufacture a positive completion. A task becomes `completed` only when its task-specific success predicate has persisted evidence. Otherwise leave it `blocked`, `pending`, or `in_progress` with a concrete fallback plan.

## Resolution Loop
1. Read the task, payload, result, error, linked lead/property/buyer, and workspace.
2. Classify the blocker.
3. Select the safest executable strategy.
4. Execute through an existing authorized worker/provider when available.
5. Check task-specific proof-of-success.
6. Persist evidence, result, blocker, fallback plan, and timestamp.
7. Complete only when proof passes; otherwise fail closed and preserve the next action.

## Blocker Classes

### provider_configuration
Signals: missing API key, provider disabled, credentials unavailable, endpoint not configured.

Preferred paths:
1. Use another already-authorized provider.
2. Use an official government/public-record source when the task permits it.
3. Prepare a manual-assisted lookup packet when automated access is not authorized.
4. Never bypass login, CAPTCHA, Cloudflare, paywall, geofence, robots/access control, or rate limits.

### evidence_gap
Signals: missing owner, deed, APN, mailing address, title fact, property fact, or source provenance.

Preferred paths:
1. County assessor/property appraiser.
2. Recorder/clerk/deed records.
3. County tax or government open data.
4. Verified property address/APN as the search seed if owner-of-record is unavailable.
5. Cross-verify consequential identity/contact facts before promotion.

### transient_provider_error
Signals: timeout, temporary outage, retryable 5xx, rate-limit response.

Preferred paths:
1. Safe retry through the authorized provider.
2. Alternate authorized provider/source.
3. Preserve partial evidence and resume later; never invent a result.

### data_conflict
Signals: owner mismatch, conflicting parcel/deed facts, ambiguous identity/contact evidence.

Preferred paths:
1. Independent authoritative source.
2. Retain each conflicting fact with provenance.
3. Do not promote the disputed field until conflict is resolved.

### compliance_or_approval
Signals: DNC/TCPA/state rule, seller authority, title authority, purchase/contract approval, POF verification, human approval.

Preferred paths:
1. Keep the consequential action blocked.
2. Continue non-contact/non-contract work in parallel: research, underwriting, title prep, buyer research, condition verification.
3. Resume only after the required approval/evidence exists.

### unclassified
1. Inspect error/result/payload.
2. Route to the closest existing worker.
3. If no executor exists, create a precise fallback plan and owner-review task rather than pretending success.

## Task-Specific Proof Examples

### owner_resolution
A provider lookup alone is not a verified owner/contact.

Positive execution proof may include:
- authorized property-provider evidence acquired; and
- county verification case created; or
- official owner-record evidence persisted; and
- any contact promotion separately satisfies the owner-resolution confidence gates.

Contact Ready never means outreach authorized.

### buyer_match
Positive proof requires a persisted deal-buyer match derived from buying-box fit. POF must be represented separately and never inferred.

### underwriting
Positive proof requires persisted ARV/repair evidence status plus computed MAO using the applicable strategy. Vacant land must not inherit SFR repair/70%-rule assumptions automatically.

### closing/title
Positive proof requires the task-specific closing/title item to be persisted as satisfied. Never close a title exception based on an estimate or narrative alone.

## Existing Engine
Backend routes:
- `GET /task-resolution/snapshot`
- `POST /task-resolution/tasks/{task_id}/resolve`
- `POST /task-resolution/run-pending`

The engine currently has an automatic executor for `owner_resolution`, routed through the existing acquisition worker. Other tasks receive blocker classification and fallback plans until an authorized task-specific executor is wired.

## Safety Boundaries
- No fabricated owners, phones, emails, comps, POF, title clearance, consent, or closing status.
- No automatic scraping of TruePeopleSearch, CyberBackgroundChecks, or similar sites without documented authorized API/license.
- No CAPTCHA/access-control bypass.
- No outreach merely because a contact was found.
- No contract, payment, offer, or regulated communication action without the applicable approval gate.
- Preserve field-level provenance and timestamps whenever evidence is promoted.

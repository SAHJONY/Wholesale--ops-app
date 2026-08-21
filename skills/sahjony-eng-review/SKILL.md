---
name: sahjony-eng-review
version: "1.0.0"
description: "Architecture and engineering-plan review for SAHJONY Wholesale OS."
user-invocable: true
---
# SAHJONY Engineering Review
Trace request -> authentication -> tenant scope -> validation -> database -> provider -> audit trail -> response -> UI. Check API contracts, transactions/idempotency, organization scoping on global IDs, background job concurrency, migrations/rollback, deterministic approval gates, provider failure isolation, AI fallback, provenance/confidence, frontend states, observability, and revision reporting. Produce architecture risks, failure modes, tests, rollout, and rollback before implementation.

---
name: sahjony-review
version: "1.0.0"
description: "Staff-engineer code review specialized for Wholesale OS correctness and production defects."
user-invocable: true
---
# SAHJONY Code Review
Prioritize: P0 security/data isolation; P0 unauthorized external action; P1 money/revenue correctness; P1 broken workflow/API contract; P1 data corruption; P2 reliability/performance; P3 maintainability. Search for global-ID access without tenant assertion, side-table scoping omissions, payload drift, approval/dispatch confusion, duplicate revenue, missing idempotency, provider facts treated as authoritative, broad exception swallowing, hardcoded readiness, stale routes, and migration/model drift. Tests alone never justify PASS; inspect invariants.

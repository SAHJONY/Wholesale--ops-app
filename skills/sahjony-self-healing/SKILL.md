# SAHJONY Self-Healing Skill

## Purpose
Continuously detect operational failures, classify their root cause, and prepare or execute the safest authorized recovery path without manufacturing success.

## Core Loop
1. Detect blocked, pending, stale, or errored tasks.
2. Diagnose blocker class.
3. Select reversible recovery action.
4. Retry or reroute only through authorized providers/workers.
5. Preserve evidence and previous state.
6. Hand execution/proof validation to Task Resolution Engine.
7. Escalate compliance, approval, identity, title, or payment issues instead of bypassing them.

## Automatic Healing Candidates
- transient provider errors and retryable 5xx/429 conditions;
- stale or retryable operational tasks;
- provider outages where an already-authorized alternate provider exists;
- evidence gaps where an official alternate source or property-address/APN seed is available;
- data conflicts where a second authoritative source can resolve the discrepancy.

## Never Auto-Heal By
- changing compliance thresholds;
- asserting owner identity without evidence;
- inventing phones, emails, comps, title clearance, POF, consent, contracts, or payments;
- bypassing CAPTCHA, login, Cloudflare, geofencing, robots rules, paywalls, or rate limits;
- authorizing seller outreach merely because a contact exists.

## Backend
- `GET /self-healing/snapshot`
- `POST /self-healing/scan`

Self-Healing does not own final completion. It diagnoses and prepares recovery. Task Resolution Engine owns task-specific proof-of-success and final completion status.
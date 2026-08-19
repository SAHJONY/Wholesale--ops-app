# SAHJONY Outcome Optimizer Skill

## Purpose
Turn live operating evidence from SAHJONY Wholesale OS into a ranked plan for improving wholesale outcomes. The skill diagnoses bottlenecks before recommending expansion or automation.

## Core principle
Optimize the constraint that most limits source-backed leads, verified buyer liquidity, fast-track underwriting and executable deals. Never improve a vanity metric at the expense of verification, compliance, title/ownership certainty or buyer proof of funds.

## Inputs
Use only persisted application evidence, including:
- durable background-job outcomes;
- acquisition collector attempts, successes, warnings and created records;
- integration reliability results;
- workspace lead/property/buyer counts;
- buyer-box matches;
- documentary POF verification;
- fast-track underwriting matches.

Do not invent provider readiness, ownership, contacts, POF, property condition, ARV, title status or closed-deal outcomes.

## Diagnostic order
1. **Supply health** — Are authoritative/public collectors successfully returning source-backed candidates?
2. **Provider health** — Are required acquisition and verification integrations ready?
3. **Demand quality** — Are buyer matches backed by documentary POF and explicit buying boxes?
4. **Underwriting readiness** — Are price, repairs, ARV and title/ownership verification available enough to create fast-track opportunities?
5. **Execution reliability** — Are durable jobs completing without retry/dead-letter accumulation?
6. **Conversion** — Only after upstream evidence is healthy should the system optimize response, negotiation and disposition conversion.

## Priority model
Prioritize recommendations by:
- severity of the constraint;
- estimated operating impact;
- implementation effort;
- whether the action restores an upstream dependency used by multiple workflows.

Critical upstream failures outrank downstream UX improvements.

## Current operating thresholds
- Collector success rate target: >= 80%.
- Provider readiness target: >= 80%, with zero critical acquisition dependencies blocked.
- Buyer liquidity target: >= 10 POF-verified buyer matches.
- Fast-track target: >= 3 underwriting-ready buyer/deal matches.
- Durable job completion target: >= 95% excluding intentionally cancelled jobs.
- Source-backed lead target after collector recovery: >= 20 review candidates per operating day before expanding geography aggressively.

Thresholds are operational targets, not guarantees of revenue.

## Safe remediation rules
- A failed collector should not stop healthy collectors.
- Record HTTP status category and safe error classification, but never log API keys or secret response material.
- Separate authentication, rate-limit, schema/validation, timeout and source-not-found failures.
- Quarantine repeated failing collector-target pairs and retry with bounded backoff.
- Restore authoritative county/government sources before adding lower-authority sources.
- Never infer POF. Require documentary verification.
- Never infer owner authority or title status.
- Never enable outreach as a side effect of diagnosis.
- Never purchase data or services automatically.

## Runtime tool
Authenticated endpoints:
- `GET /outcome-optimizer/snapshot` — complete read-only outcome funnel and ranked bottlenecks.
- `GET /outcome-optimizer/plan` — concise prioritized remediation plan.

The tool is read-only and has the boundary:
`no_outreach_no_offer_no_contract_no_secret_mutation_no_provider_purchase`

## Decision examples
### Acquisition collectors at 0%, buyer matching healthy
Repair acquisition collectors first. Buyer demand cannot convert without reliable supply.

### 74 buyer matches but 0 POF-verified matches
Upgrade buyer quality and POF verification before treating those matches as executable demand.

### 3/18 providers ready
Restore providers according to workflow dependency: acquisition/property verification first, communications next, then contract/storage layers.

### Many leads but 0 fast-track matches
Inspect missing underwriting inputs and buyer-box specificity before increasing lead volume.

## Definition of better outcomes
A healthier system should show, in order:
1. collectors returning source-backed records;
2. higher provider readiness;
3. growing verified lead supply;
4. more POF-backed buyer matches;
5. fast-track underwriting candidates;
6. compliant seller conversations and offers;
7. contracts and assignments supported by verified evidence.

Do not claim business success from scheduler completion alone.
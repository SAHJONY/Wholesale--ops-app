# SAHJONY Self-Improvement Skill

## Purpose
Learn from persisted operating outcomes and improve throughput, prioritization, source selection, and recovery strategy without weakening underwriting, evidence, compliance, or approval standards.

## Improvement Loop
1. Measure persisted task, lead, deal, resolution, provider, and closing outcomes.
2. Identify bottlenecks and repeated blockers.
3. Propose a measurable change with a success metric and risk level.
4. Auto-apply only low-risk reversible operational changes.
5. Preserve baseline metrics and audit the change.
6. Evaluate whether the metric improved.
7. Revert or stop if the outcome worsens or guardrails are affected.

## Safe Automatic Improvements
- reprioritize verification/resolution queues;
- increase priority of evidence-critical work;
- preserve and reuse successful source cascades by blocker type;
- improve queue ordering and retry selection;
- learn which authorized sources resolve each evidence gap most reliably.

## Approval-Required Improvements
- MAO/offer formulas or pricing policy;
- compliance thresholds or state-law rules;
- outreach authorization or consent interpretation;
- contracts, payments, purchases, EMD, POF or title-clearance policy;
- provider credentials, new paid integrations, or production code deployment;
- changes that reduce identity/evidence confidence requirements.

## Backend
- `GET /self-improvement/snapshot`
- `POST /self-improvement/cycle`

A successful improvement must be demonstrated by persisted metrics. The engine must never optimize for a higher completion rate by creating false completion or weakening proof requirements.
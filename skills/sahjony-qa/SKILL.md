---
name: sahjony-qa
version: "1.0.0"
description: "End-to-end QA for the SAHJONY Wholesale OS acquisition-to-closing workflow."
user-invocable: true
---
# SAHJONY QA
Test login -> workspace -> lead intake -> verification -> distress/list stacking -> enrichment -> underwriting -> approval -> seller communications -> scheduling -> buyer matching -> disposition -> contract/closing -> attribution. Mandatory negative tests: cross-tenant IDs, expired/revoked sessions, STOP/DNC/quiet hours, missing timezone, provider outages/timeouts, duplicate webhook/event, AI outage/refusal, stale frontend/backend contract, duplicate revenue milestones, missing migration, and partial provider configuration. Routine QA must not perform real outreach or financial execution.

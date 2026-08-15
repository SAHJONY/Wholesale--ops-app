# SAHJONY Nationwide Agentic Voice OS

## Objective
Build a supervised autonomous acquisition voice system that can converse naturally, use bounded tools, preserve seller/property provenance, and route work into the Wholesale OS without allowing the model to create binding offers, execute contracts, move money, clear title, or launch outbound calls on its own.

## Runtime
- Telephony: Bland/SIP infrastructure already configured by the application.
- Realtime intelligence: OpenAI Realtime (`OPENAI_REALTIME_MODEL`, default `gpt-realtime`).
- Voice: `OPENAI_REALTIME_VOICE`, default `marin`.
- Human acquisition transfer: `VOICE_HUMAN_TRANSFER_TARGET`.
- Post-call structured qualification: Phone OS Structured Outputs.

## Realtime tools
The model is allowed to use only:
1. `get_lead_context` — read tenant-scoped lead context.
2. `save_seller_pillars` — persist explicit Motivation, Timeline, Condition and Price as seller-stated claims.
3. `create_follow_up` — create a supervised task, never contact the seller directly.
4. `request_underwriting` — queue source-backed acquisition verification/underwriting.
5. `escalate_to_human` — request transfer to human acquisitions.

The model is not given functions for binding offers, contract execution, money movement, title clearance, or autonomous outbound dispatch.

## Nationwide behavior
The agent may operate in English or Spanish. Seller statements are not promoted to verified owner/property facts. State/jurisdiction compliance remains deterministic outside the model. DNC/opt-out, recording rules, approval gates, source verification, underwriting, offers, contracting and closing remain enforced by existing application services.

## Pipeline
Inbound/outbound call -> Realtime conversation -> safe tool calls -> transcript -> structured Phone OS qualification -> CRM evidence -> follow-up or human escalation -> acquisition verification job -> source-backed underwriting -> Deal Factory -> human-approved negotiation/contract flow.

## Reliability target
Every call should have a traceable provider call ID, transcript/result, qualification state, tool audit, next action and human escalation decision. Errors must fail closed for consequential actions and remain recoverable for conversational/session failures.

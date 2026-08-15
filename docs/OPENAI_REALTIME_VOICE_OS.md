# SAHJONY OpenAI Realtime Voice OS

## Purpose

Add supervised inbound and outbound phone operations to SAHJONY Wholesale OS using OpenAI Realtime as the conversational layer while preserving the existing CRM, compliance, approval, DNC, recording-consent, and audit controls.

## Architecture

Phone/SIP provider -> OpenAI Realtime SIP -> SAHJONY Voice Agent -> CRM / wholesale skills / compliance -> human transfer when required.

OpenAI is the AI conversation runtime. A telephone/SIP provider is still required to supply and route PSTN phone numbers.

## SAHJONY number map

- Telephony provider target: `bland`.
- Human transfer target: `+12816628581` (owner personal line).
- Bland outbound default from: `+13465214387`.
- Bland caller ID fallback: `+12164804413`.
- AI inbound number: must be a dedicated Bland/SIP-capable number and must NOT equal `+12816628581`.

The transfer control rejects a transfer when `VOICE_HUMAN_TRANSFER_TARGET` equals `VOICE_INBOUND_NUMBER`, preventing an AI-to-itself routing loop.

## Target Vercel values

```text
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_REALTIME_VOICE=marin
VOICE_TELEPHONY_PROVIDER=bland
VOICE_HUMAN_TRANSFER_TARGET=+12816628581
BLAND_DEFAULT_FROM_NUMBER=+13465214387
BLAND_DEFAULT_CALLER_ID=+12164804413
```

Still required before production activation:

```text
OPENAI_WEBHOOK_SECRET=<OpenAI-generated webhook signing secret>
VOICE_INBOUND_NUMBER=<dedicated Bland/SIP-capable AI number; not +12816628581>
VOICE_SIP_DOMAIN=<verified SIP routing destination/domain>
```

## Current controlled implementation

- Authenticated `/api/voice/status` reports configuration presence without returning secrets.
- Authenticated `/api/voice/calls/{callId}/accept` accepts an incoming Realtime SIP call and configures `gpt-realtime`.
- Authenticated `/api/voice/calls/{callId}/refer` transfers an active call to the configured human E.164 target.
- Authenticated `/api/voice/calls/{callId}/hangup` ends an active call.
- Authenticated `/api/voice/calls/{callId}/reject` declines an inbound call with a restricted SIP status code.
- Public `/api/voice/webhook` now verifies OpenAI webhook signatures using the official OpenAI SDK and the raw request body.
- Verified `realtime.call.incoming` events validate and return the Realtime `call_id` for the controlled runtime.
- Automatic inbound acceptance remains disabled until the verified inbound event can be persisted to CRM without relying on a browser/owner session.
- Every authenticated control action fails closed if the CRM audit write cannot be persisted.
- The main OpenAI API key remains server-side only.
- Outbound autodial is intentionally disabled until a PSTN/SIP carrier adapter is configured and connected to the existing outbound compliance + owner-approval gateway.

## Environment variables

Existing:

- `OPENAI_API_KEY` — required; secret; Production/Preview as appropriate.
- `OPENAI_VECTOR_STORE_ID` — optional knowledge base for the broader Copilot.

Voice runtime:

- `OPENAI_REALTIME_MODEL` — default: `gpt-realtime`.
- `OPENAI_REALTIME_VOICE` — default: `marin`.
- `OPENAI_VOICE_INSTRUCTIONS` — optional server-side operating instructions.
- `OPENAI_WEBHOOK_SECRET` — required for verified public OpenAI webhook ingestion.
- `VOICE_TELEPHONY_PROVIDER=bland`.
- `VOICE_INBOUND_NUMBER` — dedicated AI inbound E.164 number; do not use the human transfer line here.
- `VOICE_HUMAN_TRANSFER_TARGET=+12816628581`.
- `VOICE_SIP_DOMAIN` — carrier/SIP routing domain when applicable.
- `BLAND_DEFAULT_FROM_NUMBER=+13465214387`.
- `BLAND_DEFAULT_CALLER_ID=+12164804413`.

Provider-specific credentials must be stored server-side only. Do not place secrets in `NEXT_PUBLIC_*` variables.

## Existing safety controls to retain

The Python backend already contains voice/compliance logic for:

- automated/AI disclosure;
- recording disclosure and all-party-consent-state handling;
- verbal do-not-call detection;
- immediate contact suppression;
- exact-channel/contact compliance decisions;
- 15-minute decision TTL;
- owner approval before outbound dispatch;
- suppression re-check immediately before dispatch.

The Realtime transport must call through these gates rather than bypassing them.

## Inbound release gate

Do not enable real public inbound traffic until all are true:

1. `OPENAI_API_KEY` is present server-side.
2. `OPENAI_WEBHOOK_SECRET` is configured.
3. OpenAI webhook signature validation passes valid and invalid signature tests.
4. SIP/PSTN provider routes a dedicated AI phone number to OpenAI Realtime SIP.
5. Incoming call webhook is idempotently persisted to CRM.
6. AI disclosure occurs at the beginning of every automated call.
7. Verbal opt-out updates suppression records immediately.
8. Human transfer to `+12816628581` is tested end-to-end.
9. Call lifecycle is auditable without storing unnecessary sensitive content.

## Outbound release gate

Do not enable automated outbound dialing until all are true:

1. A carrier adapter can originate a PSTN call and bridge/route it to the Realtime session.
2. Lead/contact belongs to the authenticated workspace.
3. Fresh compliance decision passes DNC, consent, quiet-hours, channel, and exact-contact checks.
4. AI voice disclosure script passes preflight.
5. Owner approval is recorded for that outbound request.
6. Suppression is rechecked immediately before dialing.
7. The caller ID is valid and supports callbacks/opt-outs.
8. Every call attempt, provider reference, outcome, transfer, opt-out, and error is persisted.

## Production target metrics

- 0 calls placed without a valid compliance decision and approval.
- 0 API secrets exposed to client code or responses.
- 100% inbound/outbound call actions audited.
- 100% detected verbal opt-outs suppressed before another contact attempt.
- >99% successful webhook processing excluding carrier/OpenAI outages.
- P95 voice control API latency under 500 ms excluding external provider latency.

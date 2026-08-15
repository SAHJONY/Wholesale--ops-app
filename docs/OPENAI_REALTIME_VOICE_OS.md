# SAHJONY OpenAI Realtime Voice OS

## Purpose

Add supervised inbound and outbound phone operations to SAHJONY Wholesale OS using OpenAI Realtime as the conversational layer while preserving the existing CRM, compliance, approval, DNC, recording-consent, and audit controls.

## Architecture

Bland/PSTN -> OpenAI Realtime SIP -> SAHJONY Voice Agent -> CRM / wholesale skills / compliance -> human transfer when required.

OpenAI is the AI conversation runtime. Bland remains the telephony provider and number owner/routing layer.

## SAHJONY number map

- AI inbound / callback number: `+12164804413`.
- Human transfer target: `+12816628581`.
- Bland outbound default from: `+13465214387`.
- Bland caller-ID fallback: `+12164804413`.
- Telephony provider: `bland`.

The inbound/callback number and human-transfer target are intentionally different. The transfer control rejects a transfer when `VOICE_HUMAN_TRANSFER_TARGET` equals `VOICE_INBOUND_NUMBER`, preventing an AI-to-itself routing loop.

## Target Vercel values

```text
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_REALTIME_VOICE=marin
VOICE_TELEPHONY_PROVIDER=bland
VOICE_INBOUND_NUMBER=+12164804413
VOICE_HUMAN_TRANSFER_TARGET=+12816628581
BLAND_DEFAULT_FROM_NUMBER=+13465214387
BLAND_DEFAULT_CALLER_ID=+12164804413
```

Secrets / provider-derived values still required before production activation:

```text
OPENAI_WEBHOOK_SECRET=<OpenAI-generated webhook signing secret>
VOICE_SIP_DOMAIN=<verified OpenAI/Bland SIP routing destination/domain>
BLAND_AI_API_KEY=<existing Bland server-side API key>
```

Never place these secrets in `NEXT_PUBLIC_*` variables.

## Current controlled implementation

- Authenticated `/api/voice/status` reports configuration presence without returning secrets.
- Authenticated `/api/voice/calls/{callId}/accept` accepts an incoming Realtime SIP call and configures `gpt-realtime`.
- Authenticated `/api/voice/calls/{callId}/refer` transfers an active call to the configured human E.164 target.
- Authenticated `/api/voice/calls/{callId}/hangup` ends an active call.
- Authenticated `/api/voice/calls/{callId}/reject` declines an inbound call with a restricted SIP status code.
- Public `/api/voice/webhook` verifies OpenAI webhook signatures using the official OpenAI SDK and the raw request body.
- Verified `realtime.call.incoming` events validate and return the Realtime `call_id` for the controlled runtime.
- Automatic inbound acceptance remains disabled until the verified inbound event can be persisted to CRM without relying on a browser/owner session.
- Every authenticated control action fails closed if the CRM audit write cannot be persisted.
- The main OpenAI API key remains server-side only.
- Outbound autodial remains disabled until the carrier bridge is proven through the existing outbound compliance + owner-approval gateway.

## OpenAI webhook target

Configure the OpenAI project webhook to target:

```text
https://www.sahjony.com/api/voice/webhook
```

Subscribe to `realtime.call.incoming`. OpenAI sends the call ID in that event; the control plane then uses the Realtime Calls API to accept, reject, transfer, or hang up the SIP call.

Store the generated signing secret in Vercel as `OPENAI_WEBHOOK_SECRET` for Production and Preview. Do not commit the signing secret to GitHub.

## Bland SIP routing target

Bland supports inbound and outbound SIP trunks. Attach `+12164804413` to the inbound trunk and route it to the project-specific OpenAI Realtime SIP destination. Use Bland's SIP setup wizard or `POST /v1/sip/attach`; do not substitute a generic SIP hostname for the OpenAI project destination without a successful test call.

The Bland outbound number `+13465214387` remains controlled by the existing outbound gateway and must continue to pass compliance evaluation and owner approval before dispatch.

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
4. Bland routes `+12164804413` to the verified OpenAI Realtime SIP destination.
5. Incoming call webhook is idempotently persisted to CRM.
6. AI disclosure occurs at the beginning of every automated call.
7. Verbal opt-out updates suppression records immediately.
8. Human transfer to `+12816628581` is tested end-to-end.
9. Call lifecycle is auditable without storing unnecessary sensitive content.

## Outbound release gate

Do not enable automated outbound dialing until all are true:

1. Bland can originate from `+13465214387` and bridge/route the conversation to the approved Realtime session.
2. Lead/contact belongs to the authenticated workspace.
3. Fresh compliance decision passes DNC, consent, quiet-hours, channel, and exact-contact checks.
4. AI voice disclosure script passes preflight.
5. Owner approval is recorded for that outbound request.
6. Suppression is rechecked immediately before dialing.
7. The caller ID supports callbacks and opt-outs; `+12164804413` is the callback line.
8. Every call attempt, provider reference, outcome, transfer, opt-out, and error is persisted.

## Production target metrics

- 0 calls placed without a valid compliance decision and approval.
- 0 API secrets exposed to client code or responses.
- 100% inbound/outbound call actions audited.
- 100% detected verbal opt-outs suppressed before another contact attempt.
- >99% successful webhook processing excluding carrier/OpenAI outages.
- P95 voice control API latency under 500 ms excluding external provider latency.

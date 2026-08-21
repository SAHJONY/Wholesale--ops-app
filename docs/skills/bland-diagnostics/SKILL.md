# SAHJONY Bland Diagnostics Skill

## Purpose
Diagnose Bland.ai production integration failures without exposing secrets, sending SMS, recording calls, or placing a live call during the diagnostic phase.

## Trigger
Use this skill when Bland returns `AUTH_FAILURE`, `401`, webhook delivery fails, caller ID is rejected, inbound routing is missing, or the production phone stack is not proven.

## Canonical environment names
- `BLAND_AI_API_KEY`
- `BLAND_AI_WEBHOOK_SECRET`
- `BLAND_AI_WEBHOOK_SIGNATURE_HEADER`
- `BLAND_INBOUND_ORGANIZATION_ID`
- `BLAND_DEFAULT_FROM_NUMBER`
- `BLAND_INBOUND_NUMBER`
- `BLAND_PHONE_WEBHOOK_URL`
- `BLAND_INBOUND_ENABLED`
- `BLAND_AUTONOMOUS_OUTBOUND_ENABLED`

## Production webhook
`https://www.sahjony.com/api/backend/bland-phone/webhooks/call`

## Diagnostic workflow
1. Confirm the current production deployment contains the latest Bland runtime code.
2. Run `GET /internal/bland-diagnostics/run` as a manager.
3. The diagnostic normalizes common copy/paste wrappers in memory only and reports warnings without returning the secret.
4. Probe Bland `GET /v1/me` using the canonical `authorization` header.
5. If `/v1/me` returns 401/403, stop. Classify the root cause as `provider_rejected_api_key`. Do not place another test call until the key is replaced or corrected.
6. If authentication succeeds, query `GET /v1/inbound` and `GET /v1/outbound`.
7. Verify the configured outbound caller number exists in Bland outbound inventory.
8. Verify the configured inbound number exists in Bland inbound inventory.
9. Verify the inbound number's webhook matches the SAHJONY production webhook.
10. Verify recording remains disabled.
11. Only after every diagnostic check passes may an owner-authorized one-time test call be attempted.
12. A real provider `call_id` is required before declaring outbound voice operational.
13. Confirm a signed webhook POST is received before declaring the full Bland integration production-proven.

## Safety and integrity
- Never log, return, hash-display, or expose API keys or signing secrets.
- Never infer that a Vercel variable is valid merely because it exists.
- Never mark Bland production-ready after only a local/configuration check.
- Never send SMS from this skill.
- Never enable recording from this skill.
- Never place a seller call as a diagnostic shortcut.
- Owner test calls require explicit authorization and the nonce-gated one-time test route.

## Root-cause map
- `missing_api_key`: `BLAND_AI_API_KEY` is absent after normalization.
- `provider_rejected_api_key`: Bland rejected `/v1/me`; replace/correct the Bland API key in the same organization and redeploy.
- `bland_account_probe_failed`: provider or account returned a non-auth API failure; inspect Bland account/platform status.
- `configuration_mismatch`: authentication works but one or more phone/webhook checks fail.
- `healthy`: non-call diagnostics pass; proceed to a controlled owner test.

## Definition of done
Bland is production-proven only when all are true:
- `/v1/me` authenticates successfully.
- Configured caller ID is authorized for outbound use.
- Configured inbound number exists and has the correct webhook.
- Recording is disabled.
- A controlled test returns a real `call_id`.
- A signed Bland webhook POST is accepted by SAHJONY.

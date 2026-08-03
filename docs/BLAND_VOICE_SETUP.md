# Bland.ai voice: outbound calls and the signed inbound webhook

Two things have to be true before a call can happen: the credentials exist, and
the script says it is a machine. The second is enforced in code, so a
misconfigured script fails at dispatch rather than on someone's phone.

## Environment variables

All of these belong to the **backend** Vercel project, not the frontend. The
frontend never talks to Bland; it proxies to the backend, and only the backend
calls `api.bland.ai`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `BLAND_AI_API_KEY` | yes | Bland API key. Every dispatch returns 503 without it. |
| `BLAND_DEFAULT_FROM_NUMBER` | yes for outbound | Outbound caller ID in E.164, e.g. `+18505551234`. `BLAND_DEFAULT_CALLER_ID` is an alias read only if this is unset — both name the number calls are placed *from*. |
| `BLAND_INBOUND_NUMBER` | yes for inbound | The number sellers call in on. Not the same variable as the caller ID, and ideally the same number — see below. |
| `BLAND_AI_WEBHOOK_SECRET` | yes for inbound | Shared secret for the webhook signature. Unset means every delivery is rejected. |
| `BLAND_AI_WEBHOOK_SIGNATURE_HEADER` | usually no | Only if Bland's signature does not arrive in a conventional header. See below. |
| `BLAND_INBOUND_ORGANIZATION_ID` | yes for inbound | The workspace owning the receiving number. |

> The name is `BLAND_AI_API_KEY`, with the `AI`. A shorter `BLAND_API_KEY` is
> read nowhere. Setting that spelling produces a dashboard that looks configured
> and a 503 on the first call, which is the worst kind of misconfiguration
> because it fails in production rather than at setup. A test now holds
> `.env.example` and the setup checklist to the name the code actually reads.

### Paste the number bare

`+13465214387` — no quotes, spaces or dashes. Vercel stores an environment
variable exactly as pasted, and a number copied out of a chat window usually
arrives wrapped in typographic quotes: `“+13465214387”`. Those survive into
production, and the provider then rejects the call with an error that says
nothing about quoting.

The caller ID is validated as E.164 at dispatch and refused with a message that
names the problem, so a bad paste fails immediately and legibly instead of
turning into an opaque provider error.

### The caller ID should be the number that answers

If outbound calls display one number and the inbound agent answers a different
one, anyone who returns a missed call reaches the caller ID and not the agent.
On cold outbound that is a large share of the responses, since many sellers call
back rather than answer an unknown number.

It is also a regulatory point. 47 CFR 64.1601(e) requires a telemarketing call
to transmit a caller ID number the called party can dial back to make a
do-not-call request. A caller ID that rings nowhere does not satisfy that.

`GET/POST /voice/preflight` reports this under `callback`, and raises
`caller_id_does_not_reach_the_inbound_agent` in `warnings` when the two differ.
It is a warning rather than a blocker because the carrier may forward the caller
ID to the inbound line, which cannot be determined from inside the application.

The simplest correct setup is one number for both.

The voice number is **not** used for SMS. Texts require `TWILIO_FROM_NUMBER` or
`TWILIO_MESSAGING_SERVICE_SID`; a Bland voice number is not registered for A2P
10DLC, and carriers reject or fine that traffic.

Vercel applies environment variables to *new* deployments only. Adding a
variable changes nothing until the backend redeploys, and this backend has no
Git integration — see `DEPLOY_VERCEL_BACKEND.md`.

## The webhook

Point Bland at:

```
POST https://YOUR-BACKEND.vercel.app/voice/webhooks/bland
```

It is the only unauthenticated write endpoint in the application, so it verifies
an HMAC-SHA256 signature over the raw request body before parsing it. Both hex
and base64 encodings are accepted, and a `sha256=` prefix is unwrapped. The
comparison is `hmac.compare_digest`, so a wrong signature cannot be recovered a
character at a time by timing the response.

It fails closed. With no secret configured every delivery is rejected, because
an endpoint that accepts anything when misconfigured looks healthy while being
open to the internet.

### Confirming the header name

Bland's documentation was not reachable when this was built, so the exact header
name is not hardcoded. Verification tries `x-webhook-signature`,
`x-bland-signature`, `x-signature` and `signature`.

If none of those is the right one, the first delivery tells you: a rejected
delivery returns `401` with the header names it carried, and Bland shows the
response body in its delivery log.

```json
{
  "detail": {
    "error": "no_signature_header",
    "looked_for": ["x-webhook-signature", "..."],
    "received_headers": ["content-type", "x-something-signature", "..."]
  }
}
```

Set `BLAND_AI_WEBHOOK_SIGNATURE_HEADER` to whichever name appears, and the
others stop being accepted at all.

### How a call is attributed to a workspace

In order:

1. The call id matched against a `VoiceCall` or `OutboundRequest` this system
   already wrote — preferred, because it does not depend on the provider
   round-tripping anything faithfully.
2. `metadata.organization_id`, which the dispatcher sets when placing the call.
   Trusted only because the signature already proved the payload came from Bland.
3. `BLAND_INBOUND_ORGANIZATION_ID`.

A genuinely inbound call has no prior record — nobody here started it — so
without step 3 it is rejected with `422` rather than filed against a guess.
Filing one tenant's call under another is worse than losing the delivery, and a
4xx keeps it in Bland's retry log instead of disappearing into a success
response.

Redeliveries are idempotent: a second delivery of the same call id returns
`"duplicate": true` and writes nothing.

## What the code refuses to do

**Undisclosed AI voices.** The FCC ruled in February 2024 that AI-generated and
cloned voices are "artificial voice" for TCPA purposes. A call whose opening
never says it is an automated system is refused at dispatch with `422`. The
check reads `first_sentence` and `task` together, since Bland improvises the
opening from the task when no first sentence is set.

This is enforced in the dispatch path, not only in `/voice/preflight`. Preflight
is advisory and nothing obliges a caller to run it, so a gate living only there
would be a gate in name.

**Recording without consent.** Roughly a dozen states require every party to
consent, and getting it wrong there is a criminal statute rather than a
compliance ticket. Recording is off and not configurable. An unknown state is
treated as all-party, since a missing state is missing information and only one
of the two guesses carries criminal exposure. Connecticut, Michigan and Nevada
are argued either way in the sources, so they are included — over-disclosing
costs a sentence of script.

Florida is on the list, which matters because Escambia County is the first
configured market.

**Ignoring a spoken opt-out.** Asking to be taken off a list is a do-not-call
request whether it arrives by text or by voice, and the caller is under no
obligation to use a keyword. Inbound transcripts are scanned, and a request
suppresses `live_call`, `automated_call` and `sms` immediately rather than
queuing — the caller has already said it once, and a queue means the next call
may go out before anyone reads it.

"Not interested" is deliberately *not* treated as a do-not-call request. It
declines this offer, not every future one, and treating it as permanent would
silently discard leads who might sell later.

## Verifying it works

```bash
# Guards: breaks each one and checks a test notices.
python scripts/audit_guard_coverage.py

# The voice rules specifically.
python -m pytest tests/test_voice_engine.py tests/test_outbound_gateway.py
```

The mutation audit covers the webhook verifier, the all-party consent list, both
disclosure pattern sets, the verbal opt-out patterns, and the channel set the
dispatcher runs the script gate for. Each was watched to fail before being
trusted.

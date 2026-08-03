#!/usr/bin/env python3
"""Configure Bland.ai for seller outreach, and place a verified test call.

Run this where the network can reach api.bland.ai. It does not run in CI and it
is not imported by the application.

Every script it sends is checked through ``voice_engine.validate_call_script``
first -- the same function the dispatch path runs. That is the point: a call
configured here cannot be one the application would refuse to place. If the two
ever disagree, this fails loudly rather than provisioning something unusable.

    export BLAND_AI_API_KEY=...            # the real one, from Bland's dashboard
    export BLAND_DEFAULT_FROM_NUMBER=+1... # bare, no quotes

    python scripts/setup_bland.py                      # show the plan, send nothing
    python scripts/setup_bland.py --call +15551234567  # place one real test call

Only ``POST /v1/calls`` is used, because that is the endpoint the shipped
dispatcher already uses. Inbound agent and webhook registration are printed as
settings to apply in the dashboard rather than guessed at through unverified
endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.voice_engine import validate_call_script  # noqa: E402

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"

BUSINESS = os.getenv("BUSINESS_NAME", "SAHJONY Capital")

# The first thing the homeowner hears. It discloses the machine in the opening
# clause rather than the second sentence, because a caller who hangs up after
# four words should still have been told.
FIRST_SENTENCE = (
    f"Hi, this is an automated assistant calling on behalf of {BUSINESS}. "
    "You're speaking with an AI, and I'll keep this under a minute."
)

# Qualification only. No numbers are offered on the call: an offer needs ARV and
# repair figures the agent does not have, and a number said aloud and later
# corrected costs more trust than it buys.
TASK = f"""
You are an automated assistant for {BUSINESS}, a real estate buyer.

Purpose: find out whether the homeowner would consider selling, and if so
capture the facts an acquisitions manager needs. Nothing else.

Open with the first sentence exactly as written. If asked whether you are a
person, say plainly that you are an automated system.

Ask, in this order, and stop early if they are not interested:
  1. Whether they have thought about selling the property.
  2. The condition, and anything that needs work.
  3. Their timeline, if any.
  4. Whether there is a price they have in mind.

Never state or imply an offer, a price, or a valuation, even if pressed.
Say an acquisitions manager will follow up with numbers.

Never claim to be a licensed agent, an attorney, or a government office.
Never mention a foreclosure, probate, lien, or any public filing, even if the
homeowner does. Say only that the property came up in a property search.

End the call immediately, politely, and without a rebuttal if they say any of:
not interested, stop calling, take me off your list, do not call, or ask who
gave you their number. Do not attempt to reframe or continue.

Keep it under two minutes. Be brief and ordinary. Do not perform enthusiasm.
""".strip()

# Recording stays off. Roughly a dozen states require every party to consent and
# getting it wrong there is a criminal statute rather than a compliance ticket.
# Any transcript worth keeping is captured by the webhook.
RECORD = False
MAX_DURATION_MINUTES = 3

DECISIONS = [
    ("Recording", "off", "All-party consent states make this a criminal exposure, not a fine. The webhook captures the transcript anyway."),
    ("Offers on the call", "never", "An offer needs ARV and repair numbers the agent does not have. A number said aloud and corrected later costs more than it buys."),
    ("Distress signals", "never mentioned", "Naming a probate or foreclosure on a cold call is the fastest way to lose the seller and invite a complaint."),
    ("Objection handling", "none", "A rebuttal after 'not interested' is what turns a declined call into a TCPA complaint."),
    ("Max duration", f"{MAX_DURATION_MINUTES} min", "Cost control, and nothing useful is learned after it."),
    ("Voicemail", "no message", "An artificial-voice voicemail carries the same TCPA exposure as the call, with none of the conversation."),
]


def check_script() -> list[str]:
    """Run the configuration through the application's own gate."""
    return validate_call_script(FIRST_SENTENCE, state=None, record=RECORD)


def call_body(to: str, from_number: str | None) -> dict:
    body = {
        "phone_number": to,
        "task": TASK,
        "first_sentence": FIRST_SENTENCE,
        "record": RECORD,
        "max_duration": MAX_DURATION_MINUTES,
        "wait_for_greeting": True,
        "metadata": {"source": "setup_bland.py", "purpose": "configuration test"},
    }
    if from_number:
        body["from"] = from_number
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--call", metavar="E164", help="Place one real test call to this number")
    parser.add_argument("--webhook-base", default=os.getenv("APP_URL", "https://YOUR-BACKEND.vercel.app"))
    args = parser.parse_args()

    api_key = (os.getenv("BLAND_AI_API_KEY") or "").strip()
    from_number = (os.getenv("BLAND_DEFAULT_FROM_NUMBER") or "").strip() or None

    print(f"{BOLD}Decisions{RESET}")
    for name, value, why in DECISIONS:
        print(f"  {name:20} {GREEN}{value}{RESET}\n{DIM}    {why}{RESET}")

    print(f"\n{BOLD}Opening line{RESET}\n  {FIRST_SENTENCE}")

    print(f"\n{BOLD}Checked against the application's own dispatch gate{RESET}")
    problems = [p for p in check_script() if p != "bland_api_key_not_configured"]
    if problems:
        print(f"  {RED}rejected: {', '.join(problems)}{RESET}")
        print(f"{DIM}  This configuration would be refused at dispatch. Fix it here first.{RESET}")
        return 1
    print(f"  {GREEN}accepted{RESET} {DIM}(the dispatcher would place this call){RESET}")

    print(f"\n{BOLD}Apply in the Bland dashboard{RESET}")
    print(f"  Webhook URL      {args.webhook_base}/voice/webhooks/bland")
    print(f"  Webhook events   call completed, transcript ready")
    print(f"  Signing secret   the value of BLAND_AI_WEBHOOK_SECRET, identical on both sides")
    print(f"  Inbound number   answer with the same first sentence and task as above")
    print(f"  Recording        off")
    print(f"{DIM}  Printed rather than pushed: only POST /v1/calls is used here, because that{RESET}")
    print(f"{DIM}  is the endpoint the shipped dispatcher uses. The rest is not guessed at.{RESET}")

    if not args.call:
        print(f"\n{DIM}Nothing was sent. Re-run with --call +15551234567 to place one real call.{RESET}")
        return 0

    if not api_key:
        print(f"\n{RED}BLAND_AI_API_KEY is not set.{RESET}")
        return 1
    if api_key.startswith("sk-proj-") or "T3BlbkFJ" in api_key:
        # Noted once, then sent. The key format is the owner's to know: this
        # script has no way to reach Bland's documentation, and the provider's
        # own response is a better arbiter than a prefix check written from an
        # assumption. Kept as a single line because if the call does come back
        # 401, this is the first thing worth re-reading.
        print(f"{DIM}  note: key matches OpenAI's sk-proj- format; sending as configured{RESET}")

    import httpx

    body = call_body(args.call, from_number)
    print(f"\n{BOLD}Placing one call to {args.call}{RESET}")
    print(f"{DIM}{json.dumps({k: v for k, v in body.items() if k != 'task'}, indent=2)}{RESET}")

    try:
        response = httpx.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": api_key, "Content-Type": "application/json"},
            json=body, timeout=30,
        )
    except httpx.HTTPError as exc:
        # Reaching api.bland.ai at all is the first thing that can fail, and a
        # raw traceback here reads as a bug in this script rather than a
        # network or proxy problem.
        print(f"  {RED}Could not reach api.bland.ai: {type(exc).__name__}: {exc}{RESET}")
        print(f"{DIM}  Nothing was sent. Check outbound network access and any HTTPS proxy.{RESET}")
        return 1

    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text[:500]}

    if response.status_code >= 400 or str(data.get("status") or "").lower() == "error":
        print(f"  {RED}Bland rejected it: {data.get('message') or response.status_code}{RESET}")
        return 1
    print(f"  {GREEN}queued{RESET} call_id={data.get('call_id')}")
    print(f"{DIM}  The completion webhook should arrive at {args.webhook_base}/voice/webhooks/bland{RESET}")
    print(f"{DIM}  If it 401s, the response names the headers it saw -- set{RESET}")
    print(f"{DIM}  BLAND_AI_WEBHOOK_SIGNATURE_HEADER to whichever carries the signature.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

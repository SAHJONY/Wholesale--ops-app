"""Claude-backed structured reasoning for underwriting and operations.

``ARCHITECTURE.md`` lists an "Anthropic structured-output orchestrator" in the
production-hardening backlog, and ``fable5-plan.yaml`` names Anthropic as the
orchestrator provider — but the ``anthropic`` dependency was never actually
called anywhere in the codebase. This module is that orchestrator.

Three properties matter more than the model call itself:

* **Structured, not prose.** Every analysis is constrained to a JSON schema
  via ``output_config.format``, so downstream code consumes typed fields
  instead of parsing free text.
* **Never silently fabricated.** When no API key is configured, each analysis
  falls back to a deterministic rule-based version and labels itself
  ``source="deterministic"``. Callers can always tell which produced a result.
* **Inside the safety boundary.** The system prompt encodes the same approval
  gates the rest of the system enforces: the model may research, score, draft,
  and recommend, but never assert legal status, funding status, or authority
  to bind a contract.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

MODEL_MAX_TOKENS = 16_000

# Claude Opus 5 runs adaptive thinking by default; it is set explicitly here so
# the behaviour is visible at the call site rather than implied by the model ID.
THINKING_CONFIG = {"type": "adaptive"}

# Server-side refusal fallback. If the workspace has not been granted the beta,
# the request is retried once without it rather than failing the analysis.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are the underwriting and operations analyst for a residential and \
commercial real-estate wholesaling desk. You produce structured analysis that a human \
operator reviews before acting.

Operating boundary — this is not negotiable:
- You may research, score, summarize, draft, and recommend.
- You must NEVER assert that funds are available, that title is clear, that a party has \
authority to sell, or that any document is legally binding. Those are human-verified facts.
- Contracts, assignments, payments, mass campaigns, and representations about funds or \
legal status all require explicit human approval. Frame every recommendation as a proposal \
for an operator to approve, never as a completed action.
- Never invent comparable sales, ownership records, liens, contact details, or dollar \
figures. If the supplied data does not support a conclusion, say so in the relevant field \
and lower your confidence rather than filling the gap.

Analysis standards:
- Quantitative claims must trace to the numbers you were given. When you reason beyond \
them, mark it as an assumption.
- Distinguish what the data shows from what it merely suggests.
- Confidence is a calibrated 0-100 judgement about your own analysis, not a measure of how \
attractive the deal is. Thin or contradictory input data means low confidence even when the \
deal looks good.
- Prefer specific, checkable next actions ("pull the 2024 tax record for parcel X") over \
generic advice ("do more research")."""

# --- Output schemas -------------------------------------------------------
#
# Structured outputs require `additionalProperties: false` and an exhaustive
# `required` list on every object.


def _string_array(description: str, item_description: str) -> dict:
    return {
        "type": "array",
        "description": description,
        "items": {"type": "string", "description": item_description},
    }


DEAL_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "recommendation",
        "confidence",
        "summary",
        "key_risks",
        "verification_required",
        "negotiation_levers",
        "next_actions",
    ],
    "properties": {
        "recommendation": {
            "type": "string",
            "enum": ["pursue", "pursue_with_conditions", "renegotiate", "pass", "insufficient_data"],
            "description": "The action the operator should take on this deal.",
        },
        "confidence": {
            "type": "integer",
            "description": "Calibrated 0-100 confidence in this analysis given the input data quality.",
        },
        "summary": {
            "type": "string",
            "description": "Two to four sentences an operator can read in isolation and act on.",
        },
        "key_risks": _string_array(
            "Material risks to this deal, most severe first.",
            "One specific risk and why it matters to this deal.",
        ),
        "verification_required": _string_array(
            "Facts a human must independently verify before contracting.",
            "One checkable verification item.",
        ),
        "negotiation_levers": _string_array(
            "Concrete levers to improve terms with the seller.",
            "One negotiation lever grounded in the supplied data.",
        ),
        "next_actions": _string_array(
            "Ordered next actions for the operator.",
            "One specific, checkable next action.",
        ),
    },
}

SELLER_BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objective", "confidence", "opening", "discovery_questions", "likely_objections", "do_not_say"],
    "properties": {
        "objective": {"type": "string", "description": "The single outcome this call should achieve."},
        "confidence": {"type": "integer", "description": "Calibrated 0-100 confidence in this brief."},
        "opening": {"type": "string", "description": "A short, non-scripted opening the caller can adapt."},
        "discovery_questions": _string_array(
            "Questions that surface motivation, timeline, condition, and authority to sell.",
            "One discovery question.",
        ),
        "likely_objections": {
            "type": "array",
            "description": "Objections this seller is most likely to raise, with responses.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["objection", "response"],
                "properties": {
                    "objection": {"type": "string", "description": "The objection in the seller's own framing."},
                    "response": {"type": "string", "description": "An honest response that makes no unverified claim."},
                },
            },
        },
        "do_not_say": _string_array(
            "Statements the caller must avoid because they would assert unverified facts.",
            "One statement to avoid and why.",
        ),
    },
}

PORTFOLIO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "confidence", "priorities", "risks_to_revenue", "capacity_notes"],
    "properties": {
        "headline": {"type": "string", "description": "One sentence describing the state of the pipeline today."},
        "confidence": {"type": "integer", "description": "Calibrated 0-100 confidence in this assessment."},
        "priorities": {
            "type": "array",
            "description": "Ranked operating priorities for today.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "rationale", "urgency"],
                "properties": {
                    "action": {"type": "string", "description": "The specific action to take."},
                    "rationale": {"type": "string", "description": "Why this ranks where it does, citing the data."},
                    "urgency": {"type": "string", "enum": ["today", "this_week", "this_month"]},
                },
            },
        },
        "risks_to_revenue": _string_array(
            "Things most likely to cost projected revenue this cycle.",
            "One revenue risk.",
        ),
        "capacity_notes": _string_array(
            "Where the operating pipeline is constrained.",
            "One capacity or bottleneck observation.",
        ),
    },
}

ANALYSIS_SCHEMAS = {
    "deal_review": DEAL_REVIEW_SCHEMA,
    "seller_brief": SELLER_BRIEF_SCHEMA,
    "portfolio_priorities": PORTFOLIO_SCHEMA,
}


def is_configured() -> bool:
    """True when a live model call is possible."""
    return bool(settings.anthropic_api_key)


def _client():
    import anthropic  # imported lazily so the API boots without the SDK present

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _build_prompt(kind: str, payload: dict) -> str:
    instructions = {
        "deal_review": (
            "Review this wholesale deal and decide what the operator should do next. "
            "The underwriting figures were produced by a comparable-sales model and a Monte "
            "Carlo simulation; treat their confidence and warning fields as first-class "
            "evidence about how much to trust the numbers."
        ),
        "seller_brief": (
            "Prepare a call brief for an acquisitions caller speaking to this seller. "
            "The goal is to qualify motivation, timeline, condition, and authority to sell "
            "— not to close on the call."
        ),
        "portfolio_priorities": (
            "Assess this operating pipeline and rank what the team should work on. "
            "Weigh pending approvals and stalled deals against new lead volume."
        ),
    }[kind]

    return (
        f"{instructions}\n\n"
        "Here is the data. It is the complete set of facts available to you; anything "
        "absent is genuinely unknown, not omitted for brevity.\n\n"
        f"<data>\n{json.dumps(payload, indent=2, default=str)}\n</data>"
    )


def _invoke(kind: str, payload: dict) -> dict:
    """Call Claude with a schema-constrained response."""
    import anthropic

    client = _client()
    schema = ANALYSIS_SCHEMAS[kind]

    request: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": MODEL_MAX_TOKENS,
        "thinking": THINKING_CONFIG,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                # The system prompt is byte-stable across every analysis, so it
                # is the natural cache breakpoint. Only the payload varies.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema},
            "effort": settings.claude_effort,
        },
        "messages": [{"role": "user", "content": _build_prompt(kind, payload)}],
    }

    if settings.claude_server_side_fallback:
        try:
            response = client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks="default", **request
            )
        except anthropic.BadRequestError as exc:
            # The workspace may not have the fallback beta enabled. Degrading to
            # the standard endpoint is strictly better than failing the analysis.
            logger.warning("Server-side fallback unavailable, retrying without it: %s", exc)
            response = client.messages.create(**request)
    else:
        response = client.messages.create(**request)

    # A refusal returns HTTP 200 with an empty or partial content list, so the
    # stop reason has to be checked before any content is read.
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise DecisionRefused(f"Model declined this analysis (category={category})")

    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    if not text.strip():
        raise DecisionUnavailable("Model returned no analysis content")

    result = json.loads(text)
    result["source"] = "claude"
    result["model"] = getattr(response, "model", settings.claude_model)
    return result


class DecisionUnavailable(RuntimeError):
    """The model could not produce an analysis."""


class DecisionRefused(DecisionUnavailable):
    """The model's safety classifiers declined the request."""


def analyze(kind: str, payload: dict) -> dict:
    """Produce a structured analysis, falling back to deterministic rules.

    Never raises for operational reasons: a model outage degrades the quality
    of the analysis but must not take down the underwriting path. The returned
    ``source`` field records which engine produced the result.
    """
    if kind not in ANALYSIS_SCHEMAS:
        raise ValueError(f"Unknown analysis kind {kind!r}")

    if not is_configured():
        return _deterministic(kind, payload, reason="no_api_key")

    try:
        return _invoke(kind, payload)
    except DecisionRefused as exc:
        logger.warning("Claude declined %s analysis: %s", kind, exc)
        return _deterministic(kind, payload, reason="model_refusal")
    except Exception as exc:  # noqa: BLE001 - degrade rather than fail the request
        logger.exception("Claude %s analysis failed", kind)
        return _deterministic(kind, payload, reason=f"{type(exc).__name__}")


# --- Deterministic fallbacks ---------------------------------------------
#
# These are genuinely useful rule-based analyses, not placeholders. They are
# what the desk runs on when the model is unreachable.


def _deterministic(kind: str, payload: dict, *, reason: str) -> dict:
    builder = {
        "deal_review": _fallback_deal_review,
        "seller_brief": _fallback_seller_brief,
        "portfolio_priorities": _fallback_portfolio,
    }[kind]
    result = builder(payload)
    result["source"] = "deterministic"
    result["fallback_reason"] = reason
    return result


def _fallback_deal_review(payload: dict) -> dict:
    underwriting = payload.get("underwriting") or {}
    quality = underwriting.get("decision_quality") or {}
    valuation = underwriting.get("valuation") or {}
    simulation = underwriting.get("simulation") or {}

    probability = float(quality.get("probability_of_target") or 0.0)
    confidence = float(quality.get("valuation_confidence") or 0.0)
    verdict = quality.get("verdict") or "insufficient_data"

    recommendation = {
        "proceed": "pursue",
        "marginal": "renegotiate",
        "reject": "pass",
        "insufficient_data": "insufficient_data",
    }.get(verdict, "insufficient_data")

    risks: list[str] = list(valuation.get("warnings") or [])
    if probability < 0.6:
        risks.append(
            f"Assignment clears the target fee in only {probability * 100:.0f}% of simulated outcomes."
        )
    downside = simulation.get("downside_spread")
    if isinstance(downside, (int, float)) and downside < 0:
        risks.append(f"Tenth-percentile outcome loses ${abs(downside):,.0f} on the assignment.")
    if confidence < 60:
        risks.append("Valuation rests on a thin or inconsistent comparable set.")

    return {
        "recommendation": recommendation,
        "confidence": int(max(0, min(100, confidence))),
        "summary": (
            f"Comparable-sales valuation of ${float(valuation.get('arv') or 0):,.0f} "
            f"at {confidence:.0f}% confidence. At the evaluated price the assignment clears "
            f"the target fee in {probability * 100:.0f}% of simulated outcomes. "
            f"{quality.get('guidance', '')}"
        ).strip(),
        "key_risks": risks or ["No material risk detected from the supplied figures."],
        "verification_required": [
            "Confirm seller identity and authority to sell against the county record.",
            "Order a title search for liens, judgements, and unpaid taxes.",
            "Verify repair scope with an on-site walkthrough before contracting.",
        ],
        "negotiation_levers": _fallback_levers(underwriting),
        "next_actions": [
            "Review the comparable-sales grid and reject any comp that does not match on condition.",
            f"Hold the offer at or below ${float(underwriting.get('recommended_max_offer') or 0):,.0f}.",
            "Route the offer through the approval gate before sending anything to the seller.",
        ],
    }


def _fallback_levers(underwriting: dict) -> list[str]:
    levers: list[str] = []
    repairs = underwriting.get("repairs") or {}
    line_items = repairs.get("line_items") or {}
    for signal, cost in sorted(line_items.items(), key=lambda item: item[1], reverse=True)[:3]:
        levers.append(
            f"Document the {signal.replace('_', ' ')} (${cost:,.0f} of budgeted repair) as a price justification."
        )
    if repairs.get("capped_at_arv_share"):
        levers.append("Repair budget is capped by ARV share — the property may not support a rehab exit.")
    if not levers:
        levers.append("Trade a faster close or as-is terms against price.")
    return levers


def _fallback_seller_brief(payload: dict) -> dict:
    lead = payload.get("lead") or {}
    prop = payload.get("property") or {}
    signals = list(prop.get("distress_signals") or [])
    timeline = lead.get("timeline_days")

    questions = [
        "What is prompting you to consider selling right now?",
        "Is anyone else on the deed or otherwise involved in the decision?",
        "What repairs are you aware of that a buyer would need to take on?",
        "Are the property taxes and any mortgage current?",
    ]
    if timeline:
        questions.insert(1, f"You mentioned a timeline around {timeline} days — what is driving that date?")
    if "probate" in signals:
        questions.append("Has the estate been through probate, and who is the appointed representative?")
    if "pre_foreclosure" in signals:
        questions.append("Has a sale date been set, and have you spoken with the lender's loss-mitigation team?")

    return {
        "objective": "Qualify motivation, timeline, property condition, and authority to sell.",
        "confidence": 55,
        "opening": (
            f"Reference the property at {prop.get('address', 'the address on file')} and ask whether "
            "now is a workable time to talk through their situation for a few minutes."
        ),
        "discovery_questions": questions,
        "likely_objections": [
            {
                "objection": "How did you get my information?",
                "response": "Explain the specific public or licensed source the lead came from, plainly and without deflecting.",
            },
            {
                "objection": "What will you pay?",
                "response": "Explain that a number needs the condition confirmed first, and offer to walk the property.",
            },
            {
                "objection": "I want full market value.",
                "response": "Contrast a listed sale (time, repairs, commissions) with a fast as-is close, without disparaging either.",
            },
        ],
        "do_not_say": [
            "Any claim that funds are already secured or verified.",
            "Any statement about title being clear before a search is complete.",
            "Any commitment to a purchase price before the offer clears the approval gate.",
        ],
    }


def _fallback_portfolio(payload: dict) -> dict:
    pending = int(payload.get("pending_approvals") or 0)
    hot = int(payload.get("hot_leads") or 0)
    active = int(payload.get("active_deals") or 0)
    stalled = int(payload.get("stalled_deals") or 0)

    priorities = []
    if pending:
        priorities.append(
            {
                "action": f"Clear {pending} pending approval(s).",
                "rationale": "Approvals gate every outbound action; each one blocks downstream work.",
                "urgency": "today",
            }
        )
    if hot:
        priorities.append(
            {
                "action": f"Contact {hot} lead(s) scoring above the qualification threshold.",
                "rationale": "Seller motivation decays quickly; contact latency is the largest controllable loss.",
                "urgency": "today",
            }
        )
    if stalled:
        priorities.append(
            {
                "action": f"Re-engage or close out {stalled} stalled deal(s).",
                "rationale": "Stalled deals hold projected revenue that the forecast is still counting.",
                "urgency": "this_week",
            }
        )
    if not priorities:
        priorities.append(
            {
                "action": "Run acquisition sources to refill the top of the pipeline.",
                "rationale": "No approvals, hot leads, or stalled deals are competing for attention.",
                "urgency": "this_week",
            }
        )

    return {
        "headline": f"{active} active deal(s), {hot} hot lead(s), {pending} approval(s) waiting.",
        "confidence": 60,
        "priorities": priorities,
        "risks_to_revenue": (
            [f"{stalled} deal(s) have not advanced a stage recently."] if stalled else []
        )
        or ["No stalled deals detected in the current pipeline."],
        "capacity_notes": [
            f"{pending} approval(s) queued against the human review gate."
            if pending
            else "Approval queue is clear."
        ],
    }

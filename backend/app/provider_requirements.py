"""What each provider needs before it can do anything, in one place.

Two screens answered this question and disagreed, because each kept its own
copy of the rules:

* Go-live accepted *any one* of TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN or
  BLAND_AI_API_KEY as "communications ready". A Twilio account SID with no auth
  token satisfied it while being able to send precisely nothing.
* Go-live knew only SMTP_USER and SMTP_PASS for email, so a workspace running
  on RESEND_API_KEY was told email was unconfigured. Launch validation, reading
  its own list, said it was fine.

An owner cannot act on a checklist that contradicts itself, and the failure is
always the same shape: a credential that looks set and does nothing, or a
warning about something already working.

The rule this encodes is that most providers need a *set* of variables, not one
of them, and some accept more than one such set. So a requirement is a tuple of
alternatives, and each alternative is a complete group: satisfying every name in
any one group satisfies the requirement. "Any of these three" is not
expressible, deliberately -- it was the bug.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Requirement:
    id: str
    label: str
    # critical blocks going live; high should be resolved but does not block.
    severity: str
    # Each inner tuple is a complete alternative. ALL of its names must be set.
    alternatives: tuple[tuple[str, ...], ...]
    unlocks: str
    remediation: str


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        "contact_enrichment", "Contact enrichment", "critical",
        (("BATCHDATA_API_KEY", "BATCHDATA_SKIPTRACE_URL"),),
        "Owner phone numbers and mailing addresses for a verified property.",
        "Set both BatchData values; one alone authenticates nothing.",
    ),
    Requirement(
        "property_intelligence_mcp", "Property intelligence (MCP)", "high",
        (("BATCHDATA_MCP_URL", "BATCHDATA_API_TOKEN"),),
        "Property detail lookups over the BatchData MCP transport.",
        "Set both; the URL without a token is an unauthenticated endpoint.",
    ),
    Requirement(
        "communications", "Seller communications", "critical",
        # Twilio needs BOTH halves. Bland is a complete alternative on its own.
        (("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"), ("BLAND_AI_API_KEY",)),
        "Calls and texts to sellers, under the compliance gate.",
        "Set both Twilio values together, or BLAND_AI_API_KEY on its own.",
    ),
    Requirement(
        "email", "Transactional email", "high",
        (("SMTP_USER", "SMTP_PASS"), ("RESEND_API_KEY",)),
        "Buyer and seller email that is not sent from a personal account.",
        "Set the SMTP pair together, or RESEND_API_KEY on its own.",
    ),
    Requirement(
        "contracts", "Contract execution", "high",
        (("DOCUSEAL_URL", "DOCUSEAL_API_KEY"),),
        "Sending an assignment or purchase agreement for signature.",
        "Set both DocuSeal values.",
    ),
    Requirement(
        "storage", "Document storage", "high",
        (("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"),),
        "Durable storage for executed contracts and evidence.",
        "Set all three S3 values.",
    ),
    Requirement(
        "reasoning", "Reasoning engine", "high",
        (("ANTHROPIC_API_KEY",), ("OPENAI_API_KEY",)),
        "Model-backed analysis. Without it every analysis is rule-based, which "
        "is a working degradation rather than a failure.",
        "Set ANTHROPIC_API_KEY for the primary engine, or OPENAI_API_KEY alone "
        "to run only the fallback.",
    ),
)

BY_ID = {requirement.id: requirement for requirement in REQUIREMENTS}


def _is_set(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def evaluate(requirement: Requirement) -> dict:
    """Whether the requirement is met, and what is missing if not.

    Reports the *closest* unmet alternative rather than all of them, so the
    remediation is one concrete list of names instead of a decision tree. A
    half-filled group is closer than an untouched one, which is what an owner
    who has started configuring a provider wants to be told about.
    """
    for group in requirement.alternatives:
        if all(_is_set(name) for name in group):
            return {
                "id": requirement.id,
                "label": requirement.label,
                "severity": requirement.severity,
                "ready": True,
                "satisfied_by": list(group),
                "missing": [],
                "unlocks": requirement.unlocks,
                "remediation": "",
            }

    closest = max(
        requirement.alternatives,
        key=lambda group: sum(1 for name in group if _is_set(name)),
    )
    return {
        "id": requirement.id,
        "label": requirement.label,
        "severity": requirement.severity,
        "ready": False,
        "satisfied_by": None,
        "missing": [name for name in closest if not _is_set(name)],
        "unlocks": requirement.unlocks,
        "remediation": requirement.remediation,
    }


def evaluate_all() -> list[dict]:
    return [evaluate(requirement) for requirement in REQUIREMENTS]


def ready(requirement_id: str) -> bool:
    """The single answer both readiness screens ask for."""
    return evaluate(BY_ID[requirement_id])["ready"]

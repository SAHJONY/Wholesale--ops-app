"""Distress language in listing remarks, and why it does not stack.

A listing agent writing "handyman special, cash only, must sell" is telling you
something real. It is not, however, the same kind of thing as a county recorder
filing a lis pendens, and this module exists to keep those two apart.

The vocabulary here came from a market-research file of 1,650 Google search
queries -- 15 keywords crossed with 110 markets -- intended to find distressed
listings on Zillow by search engine. The keywords were worth keeping. The
delivery mechanism was not: harvesting listings through automated search
queries breaches both companies' terms, and every connector in this codebase
reads a published interface instead. So the same vocabulary is applied to
remarks arriving through the licensed listing feeds (``mls_idx``,
``fsbo_listing``), which is the lawful source for the identical signal.

Three properties of this signal drive the whole design:

* **It is marketing copy.** Written by the party trying to sell, chosen to
  attract a buyer. "Motivated seller" may mean the owner is in distress, or it
  may mean the agent wants the phone to ring. A county filing has no such
  incentive, which is why the two are scored separately.
* **It is about the listing, not the parcel.** It expires when the listing does,
  and it says nothing once the property is off market.
* **Negation is common and inverts it.** "Not a fixer upper" and "no work
  needed" are ordinary phrases in remarks. A substring match scores both as
  distress. This codebase has already shipped one substring bug -- a state
  filter matching "IN" inside "Building" -- and it excluded almost nothing for
  months.

Consequently ``listing_language`` never contributes to the stack count in
``lead_stacking``. It is reported alongside as a separate, weaker line of
evidence, labelled as what it is.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Remarks arrive as evidence like everything else: a fact recorded by a named
# source. Only the licensed listing feeds qualify -- the point of this module is
# that the signal comes from a feed the workspace is entitled to read.
REMARK_SOURCES = frozenset({"mls_idx", "fsbo_listing"})
REMARK_FIELD = "listing_remarks"

# Strength as scored in the source research, preserved rather than re-derived.
# High: the phrase is close to an admission of condition or urgency.
# Medium: consistent with distress but has innocent readings.
# Low: near-universal agent filler, kept only because its absence is mildly
# informative when every other phrase is present.
STRENGTHS: dict[str, str] = {
    "fixer upper": "high",
    "handyman special": "high",
    "investor special": "high",
    "as-is": "high",
    "needs TLC": "high",
    "probate": "high",
    "motivated seller": "high",
    "cash only": "high",
    "estate sale": "medium",
    "inherited": "medium",
    "must sell": "medium",
    "bring all offers": "medium",
    "tear down": "medium",
    "needs work": "medium",
    "priced to sell": "low",
}

WEIGHTS: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

# Written as patterns rather than literals because remarks are prose. "needs a
# little TLC" and "handyman's special" are the same claim as the canonical
# phrase, and a literal match would drop both. Every pattern is anchored with
# \b so no phrase can match inside a longer word.
PATTERNS: dict[str, re.Pattern[str]] = {
    "fixer upper": re.compile(r"\bfixer[-\s]?upper\b", re.I),
    "handyman special": re.compile(r"\bhandyman(?:'s|s)?\s+special\b", re.I),
    "investor special": re.compile(r"\binvestor(?:'s|s)?\s+special\b", re.I),
    "as-is": re.compile(r"\bas[-\s]is\b", re.I),
    # Both orders. "TLC needed" and "work needed" are as common in remarks as
    # "needs TLC", and matching only the verb-first form would miss half of
    # them -- including, importantly, the negated "no work needed", which would
    # then be invisible rather than recorded as a denial.
    "needs TLC": re.compile(
        r"\b(?:needs?\s+(?:some\s+|a\s+little\s+|a\s+bit\s+of\s+)?TLC|TLC\s+(?:is\s+)?needed)\b",
        re.I,
    ),
    "probate": re.compile(r"\bprobate\b", re.I),
    "motivated seller": re.compile(r"\bmotivated\s+seller\b", re.I),
    "cash only": re.compile(r"\bcash[-\s]only\b", re.I),
    "estate sale": re.compile(r"\bestate\s+sale\b", re.I),
    "inherited": re.compile(r"\binherit(?:ed|ance)\b", re.I),
    "must sell": re.compile(r"\bmust\s+sell\b", re.I),
    "bring all offers": re.compile(r"\bbring\s+(?:all|your|me)\s+(?:reasonable\s+)?offers\b", re.I),
    "tear down": re.compile(r"\btear[-\s]?down\b", re.I),
    "needs work": re.compile(
        r"\b(?:needs?\s+(?:some\s+|a\s+lot\s+of\s+|significant\s+)?work|work\s+(?:is\s+)?needed)\b",
        re.I,
    ),
    "priced to sell": re.compile(r"\bpriced\s+to\s+sell\b", re.I),
}

# Scanned in the text immediately preceding a match. Deliberately short: a
# window this size catches "not a fixer upper" and "no work needed" without
# reaching back into a previous sentence, where a "not" belongs to something
# else entirely.
NEGATION_WINDOW = 24
NEGATORS = re.compile(
    r"\b(?:not|no|never|isn't|is\s+not|aren't|doesn't|does\s+not|"
    r"won't|without|free\s+of|nothing)\b[^.!?]*$",
    re.I,
)


def _is_negated(text: str, start: int) -> bool:
    """Whether the match at ``start`` sits inside a negation.

    The window is clipped at sentence boundaries by the trailing ``[^.!?]*$``
    in the pattern, so "Needs work. No HOA." does not read the "No" as negating
    "needs work".
    """
    window = text[max(0, start - NEGATION_WINDOW):start]
    return NEGATORS.search(window) is not None


def scan(remarks: str | None) -> dict[str, Any]:
    """Score one listing's remarks.

    Returns matched phrases with their strength, the negated phrases separately
    (they are evidence *against* distress and worth surfacing rather than
    silently dropping), and a weighted score.
    """
    text = (remarks or "").strip()
    if not text:
        return {
            "score": 0,
            "matched": [],
            "negated": [],
            "evidence_class": "listing_language",
            "note": (
                "No listing remarks were supplied. That is an absence of text to "
                "read, not evidence the property is in good condition."
            ),
        }

    matched: list[dict[str, Any]] = []
    negated: list[str] = []
    for phrase, pattern in PATTERNS.items():
        found = pattern.search(text)
        if not found:
            continue
        if _is_negated(text, found.start()):
            negated.append(phrase)
            continue
        strength = STRENGTHS[phrase]
        matched.append({
            "phrase": phrase,
            "strength": strength,
            "weight": WEIGHTS[strength],
            "excerpt": text[max(0, found.start() - 20):found.end() + 20].strip(),
        })

    matched.sort(key=lambda m: (-m["weight"], m["phrase"]))
    score = sum(m["weight"] for m in matched)
    return {
        "score": score,
        "matched": matched,
        "negated": sorted(negated),
        "evidence_class": "listing_language",
        "note": (
            "No distress language found in these remarks."
            if not matched else
            f"{len(matched)} distress phrase(s) in agent-authored marketing copy. "
            "This is what the seller's side chose to write, not a condition any "
            "authority recorded, and it does not count toward the distress stack."
        ),
    }


def scan_facts(facts: list[Any], now: datetime) -> dict[str, Any]:
    """Scan the listing remarks among a property's facts.

    Mirrors ``lead_stacking.stack_for_facts``: a pure function over facts, so
    the scoring can be driven directly by tests without a database in between.
    An expired listing is skipped -- remarks describe a listing, and once it
    has come off market they describe nothing current.
    """
    best: Any = None
    for fact in facts:
        if fact.source not in REMARK_SOURCES or fact.field_name != REMARK_FIELD:
            continue
        if fact.expires_at is not None and fact.expires_at <= now:
            continue
        if best is None or (fact.confidence or 0) > (best.confidence or 0):
            best = fact

    if best is None:
        result = scan(None)
        result["note"] = (
            "No listing remarks have been recorded for this property from a "
            "licensed feed. That is an absence of remarks pulled, not evidence "
            "the property is in good condition."
        )
        result["source"] = None
        return result

    value = best.value_json
    if isinstance(value, dict):
        value = value.get("value", "")
    result = scan(str(value or ""))
    result["source"] = best.source
    result["observed_at"] = best.observed_at.isoformat() if best.observed_at else None
    return result

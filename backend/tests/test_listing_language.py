"""Distress language in listing remarks.

The vocabulary came from a research file of Google search queries against
Zillow. The queries were discarded -- harvesting listings that way breaches
both companies' terms -- and the keywords rehomed onto the licensed listing
feeds. What survives here is the scoring, and the two ways it can lie: by
matching inside a longer word, and by reading a negated phrase as an assertion.
"""

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from app import lead_stacking as ls
from app import listing_language as ll

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


class Fact:
    """Stand-in for IntelligenceFact; scan_facts only reads attributes."""

    def __init__(self, source=ll.REMARK_SOURCES.__iter__().__next__(), field=ll.REMARK_FIELD,
                 value="", confidence=80.0, expires_at=None, observed_at=None):
        self.source = source
        self.field_name = field
        self.value_json = value
        self.confidence = confidence
        self.expires_at = expires_at
        self.observed_at = observed_at


def phrases(result):
    return {m["phrase"] for m in result["matched"]}


# ------------------------------------------------------------- matching --

def test_each_catalogued_phrase_is_detected():
    # Every phrase in STRENGTHS must have a pattern that matches it, or the
    # catalogue silently documents a signal that never fires.
    for phrase in ll.STRENGTHS:
        assert phrase in ll.PATTERNS, phrase
        assert ll.PATTERNS[phrase].search(phrase), f"{phrase!r} does not match itself"


def test_natural_phrasing_variants_are_caught():
    assert "needs TLC" in phrases(ll.scan("Charming home, needs a little TLC."))
    assert "handyman special" in phrases(ll.scan("A true handyman's special."))
    assert "fixer upper" in phrases(ll.scan("Great fixer-upper opportunity."))
    assert "as-is" in phrases(ll.scan("Sold as is, seller will make no repairs."))


def test_both_word_orders_are_caught():
    # "work needed" is as common in remarks as "needs work". Matching only the
    # verb-first form missed it in both directions -- the distress case and the
    # negated denial that must be recorded rather than passed over in silence.
    assert "needs work" in phrases(ll.scan("Significant work needed throughout."))
    assert "needs TLC" in phrases(ll.scan("Some TLC needed in the kitchen."))


def test_phrases_do_not_match_inside_longer_words():
    # The state filter in this codebase once matched "IN" inside "Building" and
    # excluded almost nothing for months. Same failure, different vocabulary.
    assert phrases(ll.scan("Probated water rights and inheritable fixtures.")) == set()
    assert phrases(ll.scan("Cashonly Lane, Teardownsville")) == set()


# ------------------------------------------------------------- negation --

def test_negated_phrases_are_not_scored_as_distress():
    # These are ordinary remarks. Scoring them as distress would put
    # well-maintained homes at the top of the list.
    for remark in (
        "This is not a fixer upper -- fully renovated in 2024.",
        "No work needed, move-in ready.",
        "Never a tear down; structure is sound.",
        "Turnkey and free of the usual as-is caveats.",
    ):
        result = ll.scan(remark)
        assert result["matched"] == [], remark
        assert result["negated"], remark


def test_negation_does_not_reach_across_a_sentence_boundary():
    # "No HOA" must not negate "needs work" in the sentence before it.
    result = ll.scan("Needs work throughout. No HOA and no flood zone.")
    assert "needs work" in phrases(result)


def test_negated_phrases_are_reported_rather_than_dropped():
    # A remark saying the property is *not* distressed is evidence, and hiding
    # it would make an explicit denial indistinguishable from silence.
    result = ll.scan("This is not a fixer upper.")
    assert result["negated"] == ["fixer upper"]


# --------------------------------------------------------------- scoring --

def test_score_weights_strength():
    strong = ll.scan("Handyman special, cash only, motivated seller.")
    weak = ll.scan("Priced to sell.")
    assert strong["score"] > weak["score"]
    assert weak["score"] == ll.WEIGHTS["low"]


def test_every_strength_has_a_weight():
    for phrase, strength in ll.STRENGTHS.items():
        assert strength in ll.WEIGHTS, (phrase, strength)


def test_absent_remarks_do_not_read_as_a_clean_property():
    result = ll.scan("")
    assert result["score"] == 0
    assert "not evidence" in result["note"]


def test_matches_carry_an_excerpt_for_review():
    # The owner approving outreach should see the sentence, not just a label.
    result = ll.scan("Estate sale, property being sold as-is by the executor.")
    assert all(m["excerpt"] for m in result["matched"])


# ----------------------------------------------------- separation of kinds --

def test_listing_language_is_not_a_stacking_source():
    # The whole point. Marketing copy must not inflate the count of independent
    # authorities that recorded a condition.
    assert not (ll.REMARK_SOURCES & ls.DISTRESS_SOURCES)
    for source in ll.REMARK_SOURCES:
        assert source not in ls.SIGNAL_FIELDS


def test_the_note_names_the_evidence_as_marketing_copy():
    note = ll.scan("Motivated seller, must sell.")["note"]
    assert "does not count toward the distress stack" in note
    for overclaim in ("verified", "confirmed distress", "owner is desperate"):
        assert overclaim not in note.lower()


# ------------------------------------------------------------ from facts --

def test_remarks_are_read_from_a_licensed_feed():
    result = ll.scan_facts([Fact(value="Handyman special, cash only.")], NOW)
    assert "handyman special" in phrases(result)
    assert result["source"] in ll.REMARK_SOURCES


def test_facts_from_unlicensed_sources_are_ignored():
    # A remark attributed to a source outside the licensed feeds is exactly the
    # scraped input this module exists to avoid consuming.
    result = ll.scan_facts([Fact(source="zillow_search", value="Fixer upper!")], NOW)
    assert result["matched"] == []
    assert result["source"] is None


def test_an_expired_listing_stops_counting():
    stale = Fact(value="Must sell, tear down.", expires_at=NOW - timedelta(days=1))
    assert ll.scan_facts([stale], NOW)["matched"] == []


def test_the_highest_confidence_remark_wins():
    facts = [
        Fact(value="Nice home.", confidence=10.0),
        Fact(value="Investor special, needs work.", confidence=90.0),
    ]
    assert "investor special" in phrases(ll.scan_facts(facts, NOW))


def test_no_remarks_is_reported_as_absence_not_cleanliness():
    result = ll.scan_facts([], NOW)
    assert result["score"] == 0
    assert "not evidence" in result["note"]

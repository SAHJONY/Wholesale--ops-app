"""List stacking counts evidence, and only evidence that still asserts something.

The scoring is where a lead product quietly becomes dishonest: every shortcut
inflates counts, and an inflated count sends the desk to call the wrong door.
"""

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from app import lead_stacking as ls

NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


class Fact:
    """A stand-in for IntelligenceFact — the scorer only reads attributes."""

    def __init__(self, source, field=None, value=True, confidence=90.0,
                 verification_status="verified", expires_at=None, observed_at=None):
        self.source = source
        self.field_name = field if field is not None else ls.SIGNAL_FIELDS.get(source)
        self.value_json = value
        self.confidence = confidence
        self.verification_status = verification_status
        self.expires_at = expires_at
        self.observed_at = observed_at
        self.source_reference = None


def stack(*facts):
    return ls.stack_for_facts(list(facts), NOW)


# ------------------------------------------------------------- counting --

def test_independent_sources_stack():
    result = stack(Fact("tax_delinquency"), Fact("code_violation"), Fact("probate"))
    assert result["signal_count"] == 3
    assert result["tier"] == "high_conviction"


def test_one_source_is_not_a_stack():
    result = stack(Fact("tax_delinquency"))
    assert result["signal_count"] == 1
    assert result["tier"] == "single_signal"


def test_the_same_source_twice_counts_once():
    # Two tax-roll pulls of the same parcel are one source agreeing with
    # itself, not two offices independently flagging the property.
    result = stack(Fact("tax_delinquency", confidence=90), Fact("tax_delinquency", confidence=80))
    assert result["signal_count"] == 1
    assert result["signals"][0]["confidence"] == 90


def test_no_facts_reports_nothing_established_not_clean():
    # The distinction the whole framework rests on: absence of records is not
    # evidence of absence.
    result = stack()
    assert result["signal_count"] == 0
    assert result["tier"] == "none"
    assert "not evidence" in result["note"]


# ------------------------------------------------- what does not count --

def test_a_source_reporting_false_is_not_a_signal():
    # The inflation bug. A tax roll saying "not delinquent" is a useful fact
    # and the opposite of distress; counting it would score every property
    # anyone has ever pulled records for.
    result = stack(Fact("tax_delinquency", value=False), Fact("code_violation", value=True))
    assert result["signal_count"] == 1
    assert result["signals"][0]["source"] == "code_violation"


def test_falsey_shapes_are_all_treated_as_absence():
    for value in (False, None, "", "false", "No", 0, "0", "null"):
        result = stack(Fact("tax_delinquency", value=value))
        assert result["signal_count"] == 0, f"{value!r} should not assert distress"


def test_truthy_shapes_are_treated_as_assertion():
    for value in (True, "true", "Yes", 1, "open", {"value": True}):
        result = stack(Fact("tax_delinquency", value=value))
        assert result["signal_count"] == 1, f"{value!r} should assert distress"


def test_an_expired_fact_no_longer_counts():
    # A cleared code violation must stop propping the property up the list.
    expired = Fact("code_violation", expires_at=NOW - timedelta(days=1))
    live = Fact("tax_delinquency")
    result = stack(expired, live)
    assert result["signal_count"] == 1
    assert result["signals"][0]["source"] == "tax_delinquency"


def test_a_fact_expiring_later_still_counts():
    result = stack(Fact("code_violation", expires_at=NOW + timedelta(days=30)))
    assert result["signal_count"] == 1


def test_non_distress_sources_do_not_stack():
    # A cash-purchase deed and an MLS listing say real things about a property
    # but neither is a reason an owner might sell cheaply.
    result = stack(Fact("cash_purchase_deed", field="last_sale_price", value=250000),
                   Fact("mls_idx", field="mls_listed", value=True),
                   Fact("fsbo_listing", field="fsbo_listed", value=True))
    assert result["signal_count"] == 0


def test_a_fact_on_a_different_field_of_a_stacking_source_does_not_count():
    # tax_amount_due is real data, but the field that establishes the signal
    # is tax_delinquent. Counting any field from the source would make one
    # provider worth several signals.
    result = stack(Fact("tax_delinquency", field="tax_amount_due", value=4200))
    assert result["signal_count"] == 0


# ------------------------------------------------------------- reporting --

def test_verified_signals_are_counted_separately():
    result = stack(Fact("tax_delinquency", verification_status="verified"),
                   Fact("probate", verification_status="partially_verified"))
    assert result["signal_count"] == 2
    assert result["verified_signal_count"] == 1


def test_confidence_only_breaks_ties_not_ranks():
    # Two signals must outrank one, whatever the confidence figures say.
    two_weak = stack(Fact("probate", confidence=50), Fact("code_violation", confidence=50))
    one_strong = stack(Fact("tax_delinquency", confidence=99))
    assert two_weak["signal_count"] > one_strong["signal_count"]


def test_every_signal_names_the_source_that_established_it():
    # A score nobody can trace back to a record is a score nobody should act on.
    result = stack(Fact("lis_pendens"), Fact("demolition_permit"))
    for signal in result["signals"]:
        assert signal["source"] in ls.DISTRESS_SOURCES
        assert signal["field"] == ls.SIGNAL_FIELDS[signal["source"]]


def test_signal_fields_are_declared_for_every_stacking_source():
    # A distress provider with no declared signal field would silently never
    # stack, which looks identical to a provider nobody has configured.
    from app.distress_providers import PROVIDERS

    distress = {p.id for p in PROVIDERS if p.category == "distress"}
    undeclared = distress - set(ls.SIGNAL_FIELDS)
    assert not undeclared, f"distress sources missing a signal field: {undeclared}"


def test_declared_signal_fields_are_real_provider_fields():
    from app.distress_providers import PROVIDERS

    by_id = {p.id: p for p in PROVIDERS}
    for source, field in ls.SIGNAL_FIELDS.items():
        assert field in by_id[source].writable_fields, f"{source}.{field} is not a provider field"

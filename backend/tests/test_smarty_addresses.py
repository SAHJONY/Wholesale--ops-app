"""Smarty verification, and the exact strength of the claim it supports.

USPS vacancy is the most over-claimed signal in this business. "Vacant for
delivery purposes" is not "the building is empty", and the difference is a
seller who is home when someone knocks.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from app import lead_stacking as ls
from app import smarty_addresses as sa


def candidate(**analysis):
    base = {"dpv_match_code": "Y", "dpv_vacant": "N", "dpv_no_stat": "N"}
    base.update(analysis)
    return {
        "delivery_line_1": "123 Main St",
        "last_line": "Pensacola FL 32501-1234",
        "analysis": base,
        "metadata": {
            "latitude": 30.42, "longitude": -87.21,
            "county_name": "Escambia", "county_fips": "12033", "rdi": "Residential",
        },
        "components": {"zipcode": "32501", "plus4_code": "1234"},
    }


# ------------------------------------------------------------ DPV codes --

def test_confirmed_delivery_points_are_verified():
    for code in ("Y", "S", "D"):
        assert sa.interpret(candidate(dpv_match_code=code))["verified"], code


def test_unconfirmed_codes_are_not_verified():
    # "N" is not deliverable. Treating it as verified would let an address USPS
    # does not recognise satisfy the real-property rule.
    for code in ("N", "", "X"):
        assert not sa.interpret(candidate(dpv_match_code=code))["verified"], code


def test_verification_carries_coordinates_and_county():
    result = sa.interpret(candidate())
    assert result["latitude"] == 30.42
    assert result["county"] == "Escambia"
    assert result["county_fips"] == "12033"


def test_residential_delivery_indicator_is_surfaced():
    # Filters commercial addresses out before anyone pays to skip trace them.
    assert sa.interpret(candidate())["residential"] is True


# -------------------------------------------------------------- vacancy --

def test_vacancy_is_read_from_the_usps_flag():
    assert sa.interpret(candidate(dpv_vacant="Y"))["usps_reported_vacant"] is True
    assert sa.interpret(candidate(dpv_vacant="N"))["usps_reported_vacant"] is False


def test_no_stat_is_distinct_from_vacant():
    # No-stat means USPS delivers there at all -- under construction, demolished,
    # a vacant lot. Folding it into vacancy would blur two different findings.
    result = sa.interpret(candidate(dpv_vacant="N", dpv_no_stat="Y"))
    assert result["usps_no_stat"] is True
    assert result["usps_reported_vacant"] is False


def test_the_vacancy_note_does_not_overstate_the_finding():
    # The wording is the guard. "Vacant for delivery purposes" is evidence a
    # building may be empty; a forwarded owner reads identically.
    note = sa.interpret(candidate(dpv_vacant="Y"))["vacancy_note"]
    assert "delivery purposes" in note
    assert "not a finding" in note
    for overclaim in ("is empty", "is abandoned", "confirmed vacant"):
        assert overclaim not in note.lower()


def test_a_non_vacant_address_says_so_plainly():
    assert "does not report" in sa.interpret(candidate())["vacancy_note"]


# ------------------------------------------------------------- stacking --

def test_vacancy_stacks_with_county_signals():
    # The reason this connector is worth building: USPS vacancy alongside a
    # tax roll and a code case is a three-source property.
    assert "usps_vacancy" in ls.DISTRESS_SOURCES
    assert ls.SIGNAL_FIELDS["usps_vacancy"] == sa.VACANCY_FIELD


def test_the_vacancy_provider_is_registered_with_an_authority():
    from app.distress_providers import PROVIDERS

    spec = next(p for p in PROVIDERS if p.id == "usps_vacancy")
    assert spec.category == "distress"
    # Licensed, not public_record: USPS does not publish this, and marking it
    # public would put a per-address lookup into the nationwide sweep.
    assert spec.access == "licensed"
    assert spec.confidence < 88.0, "vacancy must rank below the county recorders"


def test_vacancy_does_not_enter_the_public_record_sweep():
    # A per-address lookup has no county endpoint to enumerate. If it leaked
    # into the sweep it would be reported as an unconfigured county feed.
    from app.distress_discovery import categories_without_queries

    assert "usps_vacancy" not in categories_without_queries()


# --------------------------------------------------------- configuration --

def test_missing_credentials_are_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(sa.settings, "smarty_auth_id", None)
    monkeypatch.setattr(sa.settings, "smarty_auth_token", None)
    assert sa.is_configured() is False


def test_both_halves_of_the_key_pair_are_required(monkeypatch):
    # An Auth ID without its token authenticates nothing, and half-configured
    # should read as unconfigured rather than fail at the first call.
    monkeypatch.setattr(sa.settings, "smarty_auth_id", "id-only")
    monkeypatch.setattr(sa.settings, "smarty_auth_token", None)
    assert sa.is_configured() is False

    monkeypatch.setattr(sa.settings, "smarty_auth_id", "id")
    monkeypatch.setattr(sa.settings, "smarty_auth_token", "token")
    assert sa.is_configured() is True


def test_the_address_cache_key_ignores_case_and_padding():
    # The allowance is 1,000 lookups. "123 Main St" and " 123 MAIN ST " must
    # not each spend one.
    a = sa._address_key(" 123 Main St ", "Pensacola", "FL", "32501")
    b = sa._address_key("123 MAIN ST", "pensacola", "fl", "32501")
    assert a == b

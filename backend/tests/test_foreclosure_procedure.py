"""The judicial / non-judicial split, and what it is allowed to decide.

The model exists to route configuration: it says which county office holds a
record so an operator does not point a court endpoint at a trustee state. It is
explicitly not allowed to decide anything about a property, and it must never
block a real filing that contradicts the table.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

import pytest
from fastapi import HTTPException

from app import distress_ingest, foreclosure_procedure as fp
from app.distress_providers import PROVIDERS, PROVIDERS_BY_ID


def _entry(**overrides):
    entry = {
        "id": "test_source",
        "state": "FL",
        "county": "Duval",
        "category": "lis_pendens",
        "transport": "socrata",
        "endpoint": "https://data.example.gov/resource/abcd-1234.json",
        "address_field": "property_address",
        "field_map": {"lis_pendens_filed": "filed"},
    }
    entry.update(overrides)
    return entry


def test_every_state_in_the_table_has_a_known_procedure():
    assert fp.STATE_PROCEDURE
    for state, procedure in fp.STATE_PROCEDURE.items():
        assert procedure in fp.PROCEDURES, f"{state} has unknown procedure {procedure}"
        assert len(state) == 2 and state.isupper()


def test_texas_is_absent_because_it_is_excluded_elsewhere():
    # The system rejects Texas before canonical normalization; carrying it here
    # would imply a workflow that cannot run.
    assert "TX" not in fp.STATE_PROCEDURE


def test_unlisted_state_widens_the_search_rather_than_guessing():
    assert fp.procedure_for_state("ZZ") == fp.UNKNOWN
    # A gap in the table is a gap in the table, not evidence about the state.
    assert sorted(fp.tracks_for_state("ZZ")) == [fp.JUDICIAL, fp.NON_JUDICIAL]


def test_both_track_states_search_both_offices():
    assert fp.procedure_for_state("IA") == fp.BOTH
    assert sorted(fp.tracks_for_state("IA")) == [fp.JUDICIAL, fp.NON_JUDICIAL]


def test_single_track_states_narrow_to_that_track():
    assert fp.tracks_for_state("FL") == [fp.JUDICIAL]
    assert fp.tracks_for_state("CA") == [fp.NON_JUDICIAL]


def test_guidance_names_the_offices_and_refuses_to_be_a_determination():
    detail = fp.guidance("ca")
    assert detail["state"] == "CA"
    assert detail["procedure"] == fp.NON_JUDICIAL
    assert "county_recorder" in detail["offices"]
    assert "notice_of_default" in detail["expect_documents"]
    # A judicial artefact must not be suggested in a purely non-judicial state.
    assert "foreclosure_complaint" not in detail["expect_documents"]
    assert "not legal advice" in detail["advisory"]


def test_judicial_state_expects_court_artefacts():
    detail = fp.guidance("FL")
    assert "district_or_circuit_court" in detail["offices"]
    assert "lis_pendens" in detail["expect_documents"]
    assert "notice_of_trustee_sale" not in detail["expect_documents"]


def test_procedure_is_declared_on_every_provider():
    for spec in PROVIDERS:
        assert spec.procedure in (*fp.PROCEDURES, "any"), spec.id


def test_foreclosure_categories_carry_the_right_track():
    assert PROVIDERS_BY_ID["lis_pendens"].procedure == fp.JUDICIAL
    assert PROVIDERS_BY_ID["notice_of_default"].procedure == fp.NON_JUDICIAL
    assert PROVIDERS_BY_ID["notice_of_trustee_sale"].procedure == fp.NON_JUDICIAL
    # The sale happens on either track, so it is not pinned to one.
    assert PROVIDERS_BY_ID["foreclosure_sale"].procedure == fp.BOTH
    # Non-foreclosure distress is not on a track at all.
    assert PROVIDERS_BY_ID["tax_delinquency"].procedure == "any"


def test_jurisdiction_inherits_its_category_track():
    source = distress_ingest._parse_entry(_entry())
    assert source.procedure == fp.JUDICIAL
    assert source.procedure_warning is None


def test_contradicting_the_table_warns_but_is_still_accepted():
    # A lis pendens feed in a non-judicial state is unusual, not impossible.
    # The entry must survive, because an observed filing outranks a lookup.
    source = distress_ingest._parse_entry(_entry(state="CA"))
    assert source.procedure == fp.JUDICIAL
    assert source.procedure_warning is not None
    assert "CA" in source.procedure_warning
    assert "routing help, not a rule" in source.procedure_warning


def test_both_track_state_never_warns():
    source = distress_ingest._parse_entry(_entry(state="IA"))
    assert source.procedure_warning is None


def test_a_county_may_override_the_track_it_declares():
    source = distress_ingest._parse_entry(_entry(state="IA", procedure="non_judicial"))
    assert source.procedure == fp.NON_JUDICIAL


def test_an_unknown_declared_procedure_is_rejected():
    with pytest.raises(HTTPException) as excinfo:
        distress_ingest._parse_entry(_entry(procedure="administrative"))
    assert excinfo.value.status_code == 422
    assert "administrative" in excinfo.value.detail


def test_non_foreclosure_categories_are_never_warned_about():
    source = distress_ingest._parse_entry(_entry(
        state="CA",
        category="tax_delinquency",
        field_map={"tax_delinquent": "status"},
    ))
    assert source.procedure == "any"
    assert source.procedure_warning is None


def test_procedure_never_writes_to_a_property():
    # The whole point of the guardrail: routing guidance may direct a search,
    # but no field derived from it may reach a lead.
    every_writable = {f for spec in PROVIDERS for f in spec.writable_fields}
    assert not {"procedure", "state_procedure", "foreclosure_procedure"} & every_writable

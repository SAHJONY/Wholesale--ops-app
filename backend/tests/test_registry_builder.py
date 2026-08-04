"""Column mapping for the registry builder.

The builder proposes a field map by reading real column names off a live row.
A convenient guess here becomes a wrong fact on a property, so the two rules
that stop that are pinned: never map without a positive signal, and never let
one column back two different fields.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_jurisdiction_registry import (  # noqa: E402
    FIELD_PATTERNS,
    _first_match,
    propose_field_map,
)


def test_address_column_is_found_across_naming_conventions():
    for columns, expected in [
        (["property_address", "x"], "property_address"),
        (["situs_address"], "situs_address"),
        (["SITUS_ADDR"], "SITUS_ADDR"),
        (["street_address"], "street_address"),
        (["location_address"], "location_address"),
    ]:
        assert _first_match(columns, FIELD_PATTERNS["address"]) == expected


def test_no_address_column_is_reported_as_absent():
    assert _first_match(["parcel_id", "owner"], FIELD_PATTERNS["address"]) is None


def test_a_column_never_backs_two_fields():
    # lis_pendens_filed (a flag) and lis_pendens_filed_at (a timestamp) both
    # used to claim date_filed, asserting a boolean and a date were one column.
    mapping, _ = propose_field_map(
        "lis_pendens", ["property_address", "case_number", "date_filed", "zip_code"]
    )
    assert len(set(mapping.values())) == len(mapping)
    assert mapping.get("lis_pendens_filed_at") == "date_filed"
    # With no flag-like column present, the boolean is left for a human.
    assert "lis_pendens_filed" not in mapping


def test_a_money_field_is_not_fed_by_a_status_column():
    # tax_amount_due used to map onto DELINQUENT_STATUS because unmatched
    # fields fell through to the status bucket.
    mapping, _ = propose_field_map(
        "tax_delinquency", ["SITUS_ADDR", "TAX_YEAR", "DELINQUENT_STATUS", "PARCEL_ID"]
    )
    assert "tax_amount_due" not in mapping
    assert mapping["tax_delinquent_years"] == "TAX_YEAR"


def test_a_money_field_maps_when_a_real_amount_column_exists():
    mapping, _ = propose_field_map(
        "tax_delinquency", ["addr", "amount_due", "years_delinquent", "status"]
    )
    assert mapping["tax_amount_due"] == "amount_due"
    assert mapping["tax_delinquent_years"] == "years_delinquent"


def test_unmappable_dataset_produces_an_empty_map_rather_than_noise():
    mapping, guessed = propose_field_map("foreclosure_sale", ["owner_name", "parcel", "geom"])
    assert mapping == {}
    assert guessed == []


def test_every_mapped_field_is_reported_as_guessed():
    # The caller marks entries review_required from this list, so a silently
    # mapped field would be a field nobody checks.
    mapping, guessed = propose_field_map(
        "foreclosure_sale", ["street_address", "sale_dt", "docket", "status"]
    )
    assert set(guessed) == set(mapping)


def test_mapping_only_uses_fields_the_category_may_write():
    from app.distress_providers import PROVIDERS_BY_ID

    mapping, _ = propose_field_map(
        "notice_of_trustee_sale", ["situs_address", "sale_date", "instrument_no", "status"]
    )
    allowed = set(PROVIDERS_BY_ID["notice_of_trustee_sale"].writable_fields)
    assert set(mapping) <= allowed

import asyncio

import pytest

from app.property_data import (
    PROPERTY_DATA_CREDENTIALS,
    configured_property_provider,
    property_data_configured,
)
from app.smarty_adapter import (
    SmartyConfigurationError,
    SmartyLookupError,
    _credentials,
    _split_locality,
    normalize_smarty_property,
)

# Field names mirror the official Smarty Python SDK's principal attribute model.
PRINCIPAL_PAYLOAD = [{
    "smarty_key": "1234567",
    "data_set_name": "property",
    "data_subset_name": "principal",
    "attributes": {
        "property_address_full": "100 MAIN ST",
        "property_address_city": "MIAMI",
        "property_address_state": "FL",
        "property_address_zipcode": "33101",
        "latitude": "25.7617",
        "longitude": "-80.1918",
        "parcel_account_number": "ABC-1",
        "contact_mailing_fips": "12086",
        "land_use_standard": "SINGLE FAMILY RESIDENTIAL",
        "bedrooms": "3",
        "bathrooms_total": "2.0",
        "building_sqft": "1450",
        "year_built": "1988",
        "owner_full_name": "JUAN GONZALEZ",
        "contact_full_address": "PO BOX 1, MIAMI FL 33101",
        "owner_occupancy_status": "ABSENTEE",
        "company_flag": "N",
        "assessed_value": "300000",
        "total_market_value": "350000",
        "tax_assess_year": "2025",
        "tax_billed_amount": "4500",
        "deed_sale_date": "2024-01-15",
        "deed_sale_price": "250000",
        "assessor_taxroll_update": "2026-07-01",
    },
}]


def test_normalize_smarty_principal_matches_the_shared_evidence_shape():
    result = normalize_smarty_property(PRINCIPAL_PAYLOAD)

    assert result["provider"] == "smarty"
    assert result["identifiers"] == {"smarty_key": "1234567", "apn": "ABC-1", "fips": "12086"}
    assert result["property"]["address"] == "100 MAIN ST"
    assert result["property"]["city"] == "MIAMI"
    assert result["property"]["state"] == "FL"
    assert result["property"]["zip_code"] == "33101"
    assert result["property"]["bedrooms"] == 3
    assert result["property"]["bathrooms"] == 2.0
    assert result["property"]["sqft"] == 1450
    assert result["property"]["year_built"] == 1988
    assert result["property"]["latitude"] == pytest.approx(25.7617)
    assert result["owner"]["name"] == "JUAN GONZALEZ"
    assert result["owner"]["mailing_address"] == "PO BOX 1, MIAMI FL 33101"
    assert result["valuation"]["assessed_total"] == 300000
    assert result["valuation"]["market_total"] == 350000
    assert result["valuation"]["tax_amount"] == 4500
    assert result["last_sale"]["date"] == "2024-01-15"
    assert result["last_sale"]["amount"] == 250000
    assert result["source_published_at"] == "2026-07-01"


def test_normalized_shape_matches_attom_so_callers_cannot_tell_them_apart():
    """The two providers must be interchangeable to downstream fact ingestion."""
    from app.attom_adapter import normalize_attom_property

    attom = normalize_attom_property({
        "property": [{
            "identifier": {"attomId": 1, "apn": "A", "fips": "12086"},
            "address": {"line1": "100 MAIN ST", "locality": "MIAMI", "countrySubd": "FL", "postal1": "33101"},
        }]
    })
    smarty = normalize_smarty_property(PRINCIPAL_PAYLOAD)

    assert set(smarty) == set(attom)
    for section in ("property", "owner", "valuation", "last_sale"):
        assert set(smarty[section]) == set(attom[section]), section


def test_county_verification_is_still_required_for_smarty_evidence():
    result = normalize_smarty_property(PRINCIPAL_PAYLOAD)
    assert "county_assessor_for_current_owner" in result["verification_required"]
    assert "county_recorder_for_deed_and_mortgage" in result["verification_required"]
    assert result["confidence"] < 0.9  # Never outranks an ATTOM exact match.


def test_deed_sale_wins_over_assessor_sale():
    payload = [{"attributes": {**PRINCIPAL_PAYLOAD[0]["attributes"], "sale_date": "2020-05-05", "sale_amount": "1"}}]
    result = normalize_smarty_property(payload)
    assert result["last_sale"] == {
        "date": "2024-01-15", "amount": 250000, "seller_name": None, "arms_length": None,
    }


def test_assessor_sale_used_when_no_deed_sale():
    attributes = {k: v for k, v in PRINCIPAL_PAYLOAD[0]["attributes"].items() if not k.startswith("deed_sale")}
    result = normalize_smarty_property([{"attributes": {**attributes, "sale_date": "2020-05-05", "sale_amount": "99000"}}])
    assert result["last_sale"]["date"] == "2020-05-05"
    assert result["last_sale"]["amount"] == 99000


def test_multiple_deed_owners_are_joined():
    attributes = {**PRINCIPAL_PAYLOAD[0]["attributes"]}
    attributes.pop("owner_full_name")
    attributes["deed_owner_full_name"] = "JUAN GONZALEZ"
    attributes["deed_owner_full_name2"] = "MARIA GONZALEZ"
    result = normalize_smarty_property([{"attributes": attributes}])
    assert result["owner"]["name"] == "JUAN GONZALEZ; MARIA GONZALEZ"


def test_empty_and_attributeless_responses_are_lookup_errors():
    with pytest.raises(SmartyLookupError):
        normalize_smarty_property([])
    with pytest.raises(SmartyLookupError):
        normalize_smarty_property([{"smarty_key": "1", "attributes": {}}])


def test_locality_is_split_from_the_string_callers_build():
    assert _split_locality("MIAMI, FL, 33101") == {"city": "MIAMI", "state": "FL", "zipcode": "33101"}
    assert _split_locality("MIAMI, FL") == {"city": "MIAMI", "state": "FL"}
    # A bare ZIP is not a state, so this falls through to a freeform lookup
    # rather than sending a street with a wrong locality.
    assert _split_locality("33101") == {}
    assert _split_locality("MIAMI, 33101") == {}
    assert _split_locality("") == {}


def test_half_configured_smarty_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("SMARTY_AUTH_ID", "an-id")
    monkeypatch.delenv("SMARTY_AUTH_TOKEN", raising=False)
    with pytest.raises(SmartyConfigurationError) as exc:
        _credentials()
    assert "SMARTY_AUTH_TOKEN" in str(exc.value)


def test_half_configured_smarty_does_not_satisfy_the_readiness_gate(monkeypatch):
    """The bug a flat any-of list of variable names would reintroduce."""
    monkeypatch.delenv("ATTOM_API_KEY", raising=False)
    monkeypatch.setenv("SMARTY_AUTH_ID", "an-id")
    monkeypatch.delenv("SMARTY_AUTH_TOKEN", raising=False)
    assert property_data_configured() is False

    monkeypatch.setenv("SMARTY_AUTH_TOKEN", "a-token")
    assert property_data_configured() is True


def test_unimplemented_providers_cannot_satisfy_the_gate(monkeypatch):
    """PropStream satisfied three gates for months with no adapter behind it."""
    for name in ("ATTOM_API_KEY", "SMARTY_AUTH_ID", "SMARTY_AUTH_TOKEN", "PROPERTY_DATA_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROPSTREAM_API_KEY", "a-key")
    assert property_data_configured() is False
    assert configured_property_provider() is None
    assert "propstream" not in PROPERTY_DATA_CREDENTIALS


def test_attom_is_preferred_so_existing_deployments_do_not_switch(monkeypatch):
    monkeypatch.delenv("PROPERTY_DATA_PROVIDER", raising=False)
    monkeypatch.setenv("ATTOM_API_KEY", "a-key")
    monkeypatch.setenv("SMARTY_AUTH_ID", "an-id")
    monkeypatch.setenv("SMARTY_AUTH_TOKEN", "a-token")
    assert configured_property_provider() == "attom"


def test_explicit_provider_choice_is_honoured(monkeypatch):
    monkeypatch.setenv("ATTOM_API_KEY", "a-key")
    monkeypatch.setenv("PROPERTY_DATA_PROVIDER", "smarty")
    assert configured_property_provider() == "smarty"


def test_explicit_unconfigured_provider_reports_itself_rather_than_falling_back(monkeypatch):
    from app.property_data import lookup_property

    monkeypatch.setenv("ATTOM_API_KEY", "a-key")
    monkeypatch.setenv("PROPERTY_DATA_PROVIDER", "smarty")
    monkeypatch.delenv("SMARTY_AUTH_ID", raising=False)
    monkeypatch.delenv("SMARTY_AUTH_TOKEN", raising=False)
    with pytest.raises(SmartyConfigurationError):
        asyncio.run(lookup_property("100 MAIN ST", "MIAMI, FL, 33101"))


def test_no_provider_configured_is_a_configuration_error(monkeypatch):
    from app.property_data import PropertyDataConfigurationError, lookup_property

    for name in ("ATTOM_API_KEY", "SMARTY_AUTH_ID", "SMARTY_AUTH_TOKEN", "PROPERTY_DATA_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(PropertyDataConfigurationError):
        asyncio.run(lookup_property("100 MAIN ST", "MIAMI, FL, 33101"))

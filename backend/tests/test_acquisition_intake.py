from app.acquisition_intake import _address_key, _normalize_record, parse_pasted_addresses


def test_address_key_normalizes_formatting():
    left = _address_key("123 Main St.", "Pensacola", "fl", "32501")
    right = _address_key(" 123  MAIN ST ", "PENSACOLA", "FL", "32501")
    assert left == right


def test_propstream_style_record_normalizes():
    record = _normalize_record({
        "Owner Name": "ignored",
        "owner_name": "Jane Seller",
        "property_address": "123 Main St",
        "property_city": "Pensacola",
        "property_state": "fl",
        "zip": "32501",
        "beds": "3",
        "baths": "2",
        "tags": "Absentee Owner, Tax Delinquent",
        "record_id": "PS-1",
    }, "propstream")
    assert record["seller_name"] == "Jane Seller"
    assert record["state"] == "FL"
    assert record["external_id"] == "PS-1"
    assert record["distress_signals"] == ["absentee_owner", "tax_delinquent"]


def test_unknown_source_is_safely_classified():
    record = _normalize_record({
        "address": "1 Oak Ave", "city": "Atlanta", "state": "GA", "zip_code": "30310",
        "source": "untrusted-new-provider",
    }, "csv")
    assert record["source"] == "other"


def test_parse_pasted_addresses_accepts_normal_lines_and_csv():
    records, rejected = parse_pasted_addresses(
        "100 Main St, Pensacola, FL 32501\n"
        "200 Oak Ave,Miami,FL,33101\n"
    )
    assert rejected == []
    assert records == [
        {"address": "100 Main St", "city": "Pensacola", "state": "FL", "zip_code": "32501", "source": "public_address_paste"},
        {"address": "200 Oak Ave", "city": "Miami", "state": "FL", "zip_code": "33101", "source": "public_address_paste"},
    ]


def test_parse_pasted_addresses_rejects_incomplete_and_duplicate_lines():
    records, rejected = parse_pasted_addresses(
        "100 Main St, Pensacola, FL 32501\n"
        "100 MAIN ST,Pensacola,FL,32501\n"
        "missing location\n"
    )
    assert len(records) == 1
    assert {item["reason"] for item in rejected} == {"duplicate_in_paste", "expected_street_city_state_zip"}


def test_parse_marketplace_csv_preserves_price_and_source_reference():
    records, rejected = parse_pasted_addresses(
        '300 Pine Rd,Tampa,FL,33602,"$185,000",https://www.facebook.com/marketplace/item/123\n'
    )
    assert rejected == []
    assert records[0]["asking_price"] == 185000
    assert records[0]["external_id"] == "https://www.facebook.com/marketplace/item/123"

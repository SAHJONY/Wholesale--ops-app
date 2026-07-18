from app.acquisition_intake import _address_key, _normalize_record


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

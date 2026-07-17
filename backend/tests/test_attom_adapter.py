from app.attom_adapter import normalize_attom_property


def test_normalize_attom_expanded_profile():
    payload = {
        "property": [{
            "identifier": {"attomId": 12345, "apn": "ABC-1", "fips": "12086"},
            "address": {
                "line1": "100 MAIN ST",
                "locality": "MIAMI",
                "countrySubd": "FL",
                "postal1": "33101",
                "matchCode": "Exact",
            },
            "location": {"latitude": "25.7617", "longitude": "-80.1918"},
            "summary": {"propType": "SINGLE FAMILY", "yearBuilt": "1988"},
            "building": {
                "rooms": {"beds": "3", "bathsTotal": "2.0"},
                "size": {"livingSize": "1450"},
            },
            "assessment": {
                "owner": {
                    "owner1": {"firstNameAndMi": "JUAN", "lastName": "GONZALEZ"},
                    "mailingAddressOneline": "PO BOX 1, MIAMI FL",
                    "absenteeOwnerStatus": "A",
                },
                "market": {"mktTtlValue": "350000"},
                "tax": {"taxYear": "2025", "taxAmt": "4500"},
            },
            "sale": {
                "saleTransDate": "2024-01-15",
                "amount": {"saleAmt": "250000"},
                "sellerName": "PREVIOUS OWNER",
            },
            "vintage": {"pubDate": "2026-07-01", "lastModified": "2026-07-10"},
        }]
    }

    result = normalize_attom_property(payload)

    assert result["provider"] == "attom"
    assert result["confidence"] == 0.9
    assert result["identifiers"]["attom_id"] == 12345
    assert result["property"]["state"] == "FL"
    assert result["property"]["bedrooms"] == 3
    assert result["property"]["bathrooms"] == 2.0
    assert result["property"]["sqft"] == 1450
    assert result["owner"]["name"] == "JUAN GONZALEZ"
    assert result["valuation"]["market_total"] == 350000.0
    assert result["last_sale"]["amount"] == 250000.0

from app.batchdata_adapter import normalize_batchdata_contacts


def test_normalizes_and_deduplicates_contacts():
    payload = {
        "requestId": "req-123",
        "data": {
            "result": {
                "persons": [{
                    "fullName": "Jane Owner",
                    "matchScore": 92,
                    "phones": [
                        {"phoneNumber": "3055550101", "phoneType": "mobile", "isDnc": False, "confidence": 95},
                        {"phoneNumber": "3055550101", "phoneType": "mobile", "isDnc": False, "confidence": 95},
                        {"phoneNumber": "3055550199", "phoneType": "landline", "isDnc": True},
                    ],
                    "emails": [
                        {"email": "Owner@Example.com", "isValid": True, "confidence": 90},
                        {"email": "owner@example.com", "isValid": True, "confidence": 90},
                    ],
                }]
            }
        },
    }
    result = normalize_batchdata_contacts(payload)
    assert result["owner_name"] == "Jane Owner"
    assert len(result["phones"]) == 2
    assert len(result["emails"]) == 1
    assert result["safe_phone_candidates"][0]["number"] == "3055550101"
    assert result["blocked_phone_candidates"][0]["number"] == "3055550199"
    assert result["outreach_allowed"] is False
    assert result["raw_reference"]["request_id"] == "req-123"


def test_string_contact_shapes_are_supported():
    payload = {"phones": ["7865550100"], "emails": ["seller@example.com"]}
    result = normalize_batchdata_contacts(payload)
    assert result["phones"][0]["number"] == "7865550100"
    assert result["emails"][0]["email"] == "seller@example.com"
    assert result["outreach_allowed"] is True

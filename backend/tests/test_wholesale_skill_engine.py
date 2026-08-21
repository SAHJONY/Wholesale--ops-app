from types import SimpleNamespace

from app.wholesale_skill_engine import SKILLS, _normalize_distress_signals, _rank_buyer_matches


def test_wholesale_skill_registry_covers_real_deal_workflow():
    ids = {skill["id"] for skill in SKILLS}
    assert {
        "nationwide-source-discovery",
        "owner-deed-verification",
        "distress-stacking",
        "comparable-sales-underwriting",
        "rehab-risk",
        "mao-assignment",
        "buyer-match",
        "title-closing-gate",
        "deal-ranking",
    } <= ids


def test_wholesale_skills_keep_high_risk_execution_supervised():
    by_id = {skill["id"]: skill for skill in SKILLS}
    assert by_id["comparable-sales-underwriting"]["risk"] == "financial_decision_support"
    assert by_id["title-closing-gate"]["risk"] == "legal_gate"
    assert all(skill["risk"] != "autonomous_commitment" for skill in SKILLS)


def _buyer(**overrides):
    values = {
        "id": 10,
        "name": "Verified Buyer",
        "zip_codes": ["32501"],
        "asset_types": ["single_family"],
        "min_price": 50_000,
        "max_price": 250_000,
        "max_rehab": 100_000,
        "closing_days": 14,
        "proof_of_funds_verified": True,
        "response_rate": 70,
        "reliability_score": 90,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _property_payload():
    return {
        "id": 77,
        "zip_code": "32501",
        "property_type": "single_family",
        "asking_price": 100_000,
        "repairs": 30_000,
    }


def test_buyer_match_contract_uses_ranker_output_keys():
    matches, invalid = _rank_buyer_matches(_property_payload(), [_buyer()])
    assert invalid == 0
    assert len(matches) == 1
    assert matches[0]["name"] == "Verified Buyer"
    assert matches[0]["fit_score"] is not None
    assert 0 <= matches[0]["response_probability"] <= 1


def test_malformed_buyer_does_not_crash_deal_factory_ranking():
    bad = _buyer(id=11, name="Malformed Buyer", min_price="not-a-number")
    good = _buyer(id=12, name="Usable Buyer")
    matches, invalid = _rank_buyer_matches(_property_payload(), [bad, good])
    assert invalid == 1
    assert [row["buyer_id"] for row in matches] == [12]


def test_structured_distress_evidence_is_normalized_without_losing_provenance():
    source_record = {
        "type": "foreclosure_candidate",
        "source": "public_foreclosure_screen",
        "status": "verification_required",
        "auction_date": "2026-09-01",
    }

    labels, evidence, invalid = _normalize_distress_signals([
        source_record,
        source_record,
        "tax_delinquent",
        {"source": "unknown_shape"},
    ])

    assert labels == ["foreclosure_candidate", "tax_delinquent"]
    assert evidence == [source_record, source_record, {"source": "unknown_shape"}]
    assert invalid == 1

from app.wholesale_skill_engine import SKILLS, _skill_output


def _analysis():
    return {"property": {"city": "Cleveland", "state": "OH", "zip_code": "44101", "arv": 200000, "repairs": 25000}, "owner": {"name": "Jane Owner", "type": "individual"}, "deed": {"apn": "123", "last_sale_date": "2024-01-01"}, "distress": {"signals": ["tax_delinquent"], "count": 1}, "economics": {"projected_screening_spread": 20000}, "buyers": [], "evidence": {"score": 80, "source_count": 2, "sources": [], "missing": [], "open_conflicts": []}, "decision": {"risk_score": 20, "ready_for_promotion": True, "next_action": "Human review"}}


def test_every_catalog_skill_has_a_callable_output():
    analysis = _analysis()
    assert len(SKILLS) == 9
    for skill in SKILLS:
        assert isinstance(_skill_output(skill["id"], analysis), dict)


def test_title_gate_preserves_human_approval():
    output = _skill_output("title-closing-gate", _analysis())
    assert output["cleared"] is True
    assert output["human_approval_required"] is True

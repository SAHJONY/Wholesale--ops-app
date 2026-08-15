from app.wholesale_skill_engine import SKILLS


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

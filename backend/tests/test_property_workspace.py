from api.index import app


def test_property_workspace_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/property-workspace" in paths
    assert "/property-workspace/{property_id}" in paths
    assert "/property-workspace/{property_id}/underwriting" in paths
    assert "/property-workspace/{property_id}/create-deal" in paths
    assert "get" in paths["/property-workspace"]
    assert "get" in paths["/property-workspace/{property_id}"]
    assert "put" in paths["/property-workspace/{property_id}/underwriting"]
    assert "post" in paths["/property-workspace/{property_id}/create-deal"]


def test_underwriting_contract_exposes_required_governance_inputs():
    schema = app.openapi()["components"]["schemas"]
    underwriting = schema["UnderwritingInput"]
    create_deal = schema["CreateDealInput"]
    assert set(underwriting["required"]) >= {"arv", "repairs", "confidence", "source"}
    assert "owner_confirmed" in create_deal["required"]
    assert "confidence" in create_deal["required"]

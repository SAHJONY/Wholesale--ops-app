from api.index import app


def test_property_workspace_routes_are_registered():
    paths = app.openapi()["paths"]
    assert "/property-workspace" in paths
    assert "/property-workspace/{property_id}" in paths
    assert "get" in paths["/property-workspace"]
    assert "get" in paths["/property-workspace/{property_id}"]

from app.disposition import router


def test_disposition_router_is_registered_with_operational_routes():
    paths = {route.path for route in router.routes}
    assert "/disposition/snapshot" in paths
    assert "/disposition/deals/{deal_id}/match-buyers" in paths
    assert "/disposition/deals/{deal_id}/campaigns" in paths
    assert "/disposition/deals/{deal_id}/offers" in paths
    assert "/disposition/offers/{offer_id}/select" in paths
    assert "/disposition/selections/{selection_id}/finalize" in paths

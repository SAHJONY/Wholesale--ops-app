from pathlib import Path

from api.index import app


def test_closing_command_routes_remain_mounted_for_supported_markets():
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/closing-command/snapshot" in routes
    assert "/closing-command/deals/{deal_id}/initialize" in routes
    assert "/disposition/snapshot" in routes


def test_closing_command_has_no_legacy_texas_exclusion():
    source = (Path(__file__).resolve().parents[1] / "app" / "closing_command.py").read_text()
    assert "Texas is excluded from SAHJONY acquisition workflows" not in source
    assert 'str(prop.state or "").upper() == "TX"' not in source

from pathlib import Path

from api.index import app
from app.operating_system import DEFAULT_MARKETS


def test_contract_and_closing_routes_remain_mounted_for_supported_markets():
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/deal-execution/snapshot" in routes
    assert "/deal-execution/deals/{deal_id}/packets" in routes
    assert "/closing-command/snapshot" in routes
    assert "/closing-command/deals/{deal_id}/initialize" in routes
    assert "/disposition/snapshot" in routes


def test_revenue_path_has_no_legacy_texas_exclusion():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    for module in ("operating_system.py", "deal_execution.py", "closing_command.py", "disposition.py"):
        source = (app_dir / module).read_text()
        assert "Texas is excluded from SAHJONY acquisition workflows" not in source
        assert '"exclude_states": ["TX"]' not in source
        assert 'str(prop.state or "").upper() == "TX"' not in source


def test_houston_texas_is_in_default_operating_markets():
    assert "Houston TX" in DEFAULT_MARKETS

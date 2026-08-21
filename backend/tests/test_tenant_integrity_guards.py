from types import SimpleNamespace

import pytest

from app.sms_attribution_models import _guard_attribution_lead_workspace
from app.sms_models import _guard_sms_lead_workspace


class Result:
    def __init__(self, found: bool):
        self.found = found

    def first(self):
        return (1,) if self.found else None


class Connection:
    def __init__(self, found: bool):
        self.found = found

    def execute(self, _statement):
        return Result(self.found)


def test_sms_message_rejects_cross_tenant_lead_link():
    target = SimpleNamespace(organization_id=1, lead_id=99)
    with pytest.raises(ValueError, match="outside this workspace"):
        _guard_sms_lead_workspace(None, Connection(False), target)


def test_sms_message_accepts_workspace_lead_link():
    target = SimpleNamespace(organization_id=1, lead_id=7)
    _guard_sms_lead_workspace(None, Connection(True), target)


def test_attribution_event_rejects_cross_tenant_lead_link():
    target = SimpleNamespace(organization_id=1, lead_id=99)
    with pytest.raises(ValueError, match="outside this workspace"):
        _guard_attribution_lead_workspace(None, Connection(False), target)

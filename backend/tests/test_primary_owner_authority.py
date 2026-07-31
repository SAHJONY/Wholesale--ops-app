from app.auth import ROLE_RANK, _is_primary_owner, _primary_owner_email


def test_primary_owner_has_highest_role_rank():
    assert ROLE_RANK["owner"] == max(ROLE_RANK.values())
    assert ROLE_RANK["owner"] > ROLE_RANK["admin"]


def test_configured_primary_owner_email_is_recognized(monkeypatch):
    monkeypatch.setenv("PRIMARY_OWNER_EMAIL", "owner@example.com")
    assert _primary_owner_email() == "owner@example.com"
    assert _is_primary_owner("OWNER@example.com") is True
    assert _is_primary_owner("manager@example.com") is False


def test_default_primary_owner_email_is_stable(monkeypatch):
    monkeypatch.delenv("PRIMARY_OWNER_EMAIL", raising=False)
    assert _is_primary_owner("sahjonycapitalllc@outlook.com") is True

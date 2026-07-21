from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import DeclarativeBase

from app import schema_policy


class TestBase(DeclarativeBase):
    pass


class Example(TestBase):
    __tablename__ = "schema_policy_examples"
    id = Column(Integer, primary_key=True)


def test_compatibility_mode_creates_missing_tables(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setenv("SCHEMA_MODE", "compatibility")

    state = schema_policy.configure_schema(TestBase, engine)

    assert state.mode == "compatibility"
    assert state.runtime_create_attempted is True
    assert state.missing_tables == []
    assert state.strict_ready is True


def test_strict_mode_reports_missing_without_creating(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setenv("SCHEMA_MODE", "strict")

    state = schema_policy.configure_schema(TestBase, engine)

    assert state.mode == "strict"
    assert state.runtime_create_attempted is False
    assert state.missing_tables == ["schema_policy_examples"]
    assert state.strict_ready is False

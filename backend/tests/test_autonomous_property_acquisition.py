import asyncio

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auth import Principal
from app.autonomous_property_acquisition import (
    _extract_records,
    acquisition_feed_status,
    run_autonomous_property_acquisition,
)
from app.database import Base
from app.models import Lead


def principal() -> Principal:
    return Principal(
        organization_id=42,
        organization_name="Test",
        user_id=7,
        email="owner@example.com",
        name="Owner",
        role="owner",
    )


def test_feed_defaults_disabled_and_review_only(monkeypatch):
    monkeypatch.delenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", raising=False)
    monkeypatch.delenv("AUTONOMOUS_PROPERTY_FEED_URL", raising=False)
    status = acquisition_feed_status()
    assert status["enabled"] is False
    assert status["review_only"] is True
    assert status["outreach_allowed"] is False


def test_feed_rejects_more_than_run_limit():
    with pytest.raises(RuntimeError, match="exceeds"):
        _extract_records([{}] * 1001)


def test_autonomous_feed_creates_non_contactable_property_candidate(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTONOMOUS_PROPERTY_ACQUISITION", "true")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_URL", "https://data.example.gov/properties")
    monkeypatch.setenv("AUTONOMOUS_PROPERTY_FEED_SOURCE", "county")
    payload = {
        "records": [{
            "external_id": "parcel-1",
            "address": "100 Main St",
            "city": "Pensacola",
            "state": "FL",
            "zip_code": "32501",
            "owner_name": "Must Not Become Contact",
            "phone": "+15555550100",
            "email": "private@example.com",
        }]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json=payload)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    transport = httpx.MockTransport(handler)
    with Session(engine) as db:
        async def execute():
            async with httpx.AsyncClient(transport=transport) as client:
                return await run_autonomous_property_acquisition(db, principal(), client=client)

        result = asyncio.run(execute())
        lead = db.scalar(select(Lead))
        assert result["created"] == 1
        assert result["review_only"] is True
        assert lead is not None
        assert lead.status == "property_candidate"
        assert lead.seller_name == "Unverified owner"
        assert lead.phone == "unknown"
        assert lead.email is None

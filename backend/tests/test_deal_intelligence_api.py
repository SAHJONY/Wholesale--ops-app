"""End-to-end tests for the decision-intelligence API surface.

These run against the real app with a real database, so they also cover the
workspace-scoping behaviour: a caller must only ever see their own leads,
buyers, and deals.
"""

import os
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api.index import app
from app.auth_models import WorkspaceEntity
from app.database import SessionLocal
from app.models import Buyer, Deal, Lead, Property

client = TestClient(app)


def bootstrap_workspace():
    """Create an isolated workspace and return its owner API key."""
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/auth/bootstrap",
        json={
            "organization_name": f"Test Desk {suffix}",
            "owner_email": f"owner-{suffix}@example.com",
            "owner_name": "Test Owner",
        },
        headers={"X-Bootstrap-Secret": os.environ["BOOTSTRAP_SECRET"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["api_key"]


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def seed_workspace(key, *, leads=2, buyers=2, deals=1, closed=0, dead=0):
    """Populate a workspace directly, linking every entity to the org."""
    me = client.get("/auth/me", headers=auth(key))
    assert me.status_code == 200, me.text
    organization_id = me.json()["organization_id"]

    created = {"leads": [], "buyers": [], "deals": []}
    with SessionLocal() as db:
        def link(entity_type, entity_id):
            db.add(
                WorkspaceEntity(
                    organization_id=organization_id, entity_type=entity_type, entity_id=entity_id
                )
            )

        for index in range(leads + closed + dead):
            lead = Lead(
                seller_name=f"Seller {index}",
                phone=f"555-01{index:02d}",
                source="test",
                motivation_score=40 + index * 5,
                equity_score=50,
                distress_score=30,
                timeline_days=45,
            )
            lead.property = Property(
                address=f"{index} Test St",
                city="Pensacola",
                state="FL",
                zip_code="32501",
                property_type="single_family",
                sqft=1500,
                arv=250_000,
                repairs=40_000,
                mao=100_000,
                distress_signals=["vacant"],
            )
            db.add(lead)
            db.flush()
            link("lead", lead.id)
            created["leads"].append(lead.id)

            stage = "qualified"
            if index >= leads and index < leads + closed:
                stage = "closed"
            elif index >= leads + closed:
                stage = "dead"
            if index < leads + closed + dead and (index < deals or stage != "qualified"):
                deal = Deal(
                    property_id=lead.property.id,
                    stage=stage,
                    projected_assignment_fee=15_000,
                )
                db.add(deal)
                db.flush()
                link("deal", deal.id)
                created["deals"].append(deal.id)

        for index in range(buyers):
            buyer = Buyer(
                name=f"Buyer {index}",
                phone=f"555-02{index:02d}",
                zip_codes=["32501"],
                asset_types=["single_family"],
                min_price=50_000,
                max_price=200_000,
                max_rehab=80_000,
                response_rate=60,
                reliability_score=75,
                proof_of_funds_verified=True,
            )
            db.add(buyer)
            db.flush()
            link("buyer", buyer.id)
            created["buyers"].append(buyer.id)

        db.commit()
    return created


@pytest.fixture(scope="module")
def workspace():
    key = bootstrap_workspace()
    seeded = seed_workspace(key, leads=3, buyers=2, deals=2, closed=1, dead=1)
    return {"key": key, "seeded": seeded}


class TestAuthentication:
    def test_every_route_requires_a_key(self):
        for path in (
            "/deal-intelligence/status",
            "/deal-intelligence/briefing",
            "/deal-intelligence/forecast",
            "/deal-intelligence/leads/ranked",
        ):
            assert client.get(path).status_code == 401, path

    def test_an_invalid_key_is_rejected(self):
        assert client.get(
            "/deal-intelligence/status", headers=auth("sahjony_live_bogus")
        ).status_code == 401


class TestStatus:
    def test_reports_capabilities_and_engine(self, workspace):
        response = client.get("/deal-intelligence/status", headers=auth(workspace["key"]))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["capabilities"]["monte_carlo_underwriting"] is True
        assert body["reasoning_model"]["engine"] in {"claude", "deterministic"}
        assert "scoring_model" in body


class TestUnderwriting:
    def payload(self, **overrides):
        base_date = date(2026, 5, 1)
        body = {
            "subject": {
                "address": "12 Oak St",
                "sqft": 1500,
                "bedrooms": 3,
                "bathrooms": 2,
                "year_built": 1985,
                "condition": "moderate",
                "distress_signals": ["roof_damage"],
            },
            "comparables": [
                {
                    "address": f"{index} Comp St",
                    "sale_price": 250_000 + index * 3_000,
                    "sale_date": str(base_date - timedelta(days=index * 20)),
                    "sqft": 1480 + index * 20,
                    "bedrooms": 3,
                    "bathrooms": 2,
                    "year_built": 1985,
                    "distance_miles": 0.4,
                    "condition": "good",
                }
                for index in range(5)
            ],
        }
        body.update(overrides)
        return body

    def test_produces_a_full_underwriting_record(self, workspace):
        response = client.post(
            "/deal-intelligence/underwrite",
            json=self.payload(),
            headers=auth(workspace["key"]),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valuation"]["arv"] > 0
        assert body["simulation"]["iterations"] > 0
        assert body["recommended_max_offer"] >= 0
        assert body["analysis"]["source"] in {"claude", "deterministic"}

    def test_comparables_are_required(self, workspace):
        response = client.post(
            "/deal-intelligence/underwrite",
            json=self.payload(comparables=[]),
            headers=auth(workspace["key"]),
        )
        assert response.status_code == 422

    def test_malformed_comparables_are_rejected_with_a_clear_error(self, workspace):
        body = self.payload()
        body["comparables"][0]["sale_date"] = "not-a-date"
        response = client.post(
            "/deal-intelligence/underwrite", json=body, headers=auth(workspace["key"])
        )
        assert response.status_code == 422
        assert "Invalid comparable" in response.json()["detail"]

    def test_analysis_can_be_skipped(self, workspace):
        response = client.post(
            "/deal-intelligence/underwrite",
            json=self.payload(include_analysis=False),
            headers=auth(workspace["key"]),
        )
        assert "analysis" not in response.json()


class TestRankedLeads:
    def test_returns_ranked_workspace_leads(self, workspace):
        response = client.get("/deal-intelligence/leads/ranked", headers=auth(workspace["key"]))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["lead_count"] >= 3
        probabilities = [row["probability"] for row in body["leads"]]
        assert probabilities == sorted(probabilities, reverse=True)
        assert all(0.0 <= value <= 1.0 for value in probabilities)

    def test_only_returns_leads_from_the_callers_workspace(self, workspace):
        other_key = bootstrap_workspace()
        seed_workspace(other_key, leads=1, buyers=0, deals=0)

        mine = client.get(
            "/deal-intelligence/leads/ranked", headers=auth(workspace["key"])
        ).json()
        theirs = client.get("/deal-intelligence/leads/ranked", headers=auth(other_key)).json()

        my_ids = {row["lead_id"] for row in mine["leads"]}
        their_ids = {row["lead_id"] for row in theirs["leads"]}
        assert my_ids
        assert their_ids
        assert my_ids.isdisjoint(their_ids)

    def test_limit_is_bounded(self, workspace):
        response = client.get(
            "/deal-intelligence/leads/ranked?limit=1", headers=auth(workspace["key"])
        )
        assert len(response.json()["leads"]) == 1


class TestCallBrief:
    def test_returns_a_brief_with_a_compliance_reminder(self, workspace):
        lead_id = workspace["seeded"]["leads"][0]
        response = client.get(
            f"/deal-intelligence/leads/{lead_id}/call-brief", headers=auth(workspace["key"])
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["brief"]["discovery_questions"]
        assert "quiet hours" in body["compliance_reminder"]
        assert 0.0 <= body["scoring"]["probability"] <= 1.0

    def test_a_lead_outside_the_workspace_is_not_found(self, workspace):
        other_key = bootstrap_workspace()
        seeded = seed_workspace(other_key, leads=1, buyers=0, deals=0)
        response = client.get(
            f"/deal-intelligence/leads/{seeded['leads'][0]}/call-brief",
            headers=auth(workspace["key"]),
        )
        assert response.status_code == 404


class TestForecastAndBriefing:
    def test_forecast_discounts_the_nominal_pipeline(self, workspace):
        response = client.get("/deal-intelligence/forecast", headers=auth(workspace["key"]))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["expected_revenue"] <= body["nominal_pipeline_value"]
        assert body["conversion_rates"]

    def test_briefing_combines_forecast_leads_and_analysis(self, workspace):
        response = client.get("/deal-intelligence/briefing", headers=auth(workspace["key"]))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["analysis"]["priorities"]
        assert "expected_revenue" in body["forecast"]
        assert body["leads"]["total"] >= 3
        assert "scoring_model" in body


class TestDispositionPlan:
    def test_plans_assignments_and_requires_approval(self, workspace):
        response = client.post(
            "/deal-intelligence/disposition/plan",
            json={"buyer_capacity": 2},
            headers=auth(workspace["key"]),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["approval_required"] is True
        assert body["expected_revenue"] >= 0
        assert body["parameters"]["buyer_capacity"] == 2

    def test_a_workspace_without_buyers_is_told_why(self):
        key = bootstrap_workspace()
        seed_workspace(key, leads=1, buyers=0, deals=1)
        response = client.post(
            "/deal-intelligence/disposition/plan", json={}, headers=auth(key)
        )
        assert response.status_code == 422
        assert "buyers" in response.json()["detail"].lower()


class TestMarketData:
    """The free public market-data surface.

    Market data is monkeypatched here so the suite never depends on outbound
    network access; the connectors themselves are covered in test_market_data.
    """

    def context(self):
        from app.market_data import MarketContext

        return MarketContext(
            zip_code="32501",
            median_home_value=145_600.0,
            median_home_value_moe=12_800.0,
            median_gross_rent=1_024.0,
            owner_occupancy_rate=0.4518,
            vacancy_rate=0.1793,
            vintage="2023",
            retrieved_at="2026-07-28T00:00:00+00:00",
        )

    def appreciation(self, measured=True):
        from app.market_data import AppreciationRate

        return AppreciationRate(
            annual_rate=0.041,
            monthly_rate=0.003354,
            level="zip" if measured else "fallback",
            area="32501",
            period="2023",
            measured=measured,
            source="FHFA House Price Index",
            retrieved_at="2026-07-28T00:00:00+00:00",
        )

    def patch_live(self, monkeypatch):
        from app import market_data

        monkeypatch.setattr(market_data, "fetch_market_context", lambda *a, **k: self.context())
        monkeypatch.setattr(market_data, "fetch_appreciation", lambda *a, **k: self.appreciation())

    def patch_blocked(self, monkeypatch):
        from app import market_data

        def unavailable(*args, **kwargs):
            raise market_data.MarketDataUnavailable("HTTP 403 from an egress proxy")

        monkeypatch.setattr(market_data, "fetch_market_context", unavailable)
        monkeypatch.setattr(market_data, "fetch_appreciation", unavailable)

    def test_market_endpoint_returns_census_and_fhfa_data(self, workspace, monkeypatch):
        self.patch_live(monkeypatch)
        response = client.get("/deal-intelligence/market/32501", headers=auth(workspace["key"]))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["context"]["median_home_value"] == 145_600.0
        assert body["appreciation"]["measured"] is True
        assert all(source["cost"] == "free" for source in body["sources"])

    def test_market_endpoint_reports_degradation_rather_than_faking_data(
        self, workspace, monkeypatch
    ):
        self.patch_blocked(monkeypatch)
        response = client.get("/deal-intelligence/market/32501", headers=auth(workspace["key"]))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert "network access" in body["detail"]
        assert body["appreciation"]["measured"] is False
        assert body["errors"]

    def test_market_endpoint_validates_the_zip(self, workspace):
        assert client.get(
            "/deal-intelligence/market/abcde", headers=auth(workspace["key"])
        ).status_code == 422

    def test_market_endpoint_requires_authentication(self):
        assert client.get("/deal-intelligence/market/32501").status_code == 401

    def test_underwriting_uses_measured_appreciation_when_available(
        self, workspace, monkeypatch
    ):
        self.patch_live(monkeypatch)
        body = TestUnderwriting().payload()
        body["subject"]["zip_code"] = "32501"
        body["subject"]["state"] = "FL"
        response = client.post(
            "/deal-intelligence/underwrite", json=body, headers=auth(workspace["key"])
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["valuation"]["appreciation"]["measured"] is True
        assert result["market"]["plausibility"]["checked"] is True

    def test_underwriting_survives_a_market_data_outage(self, workspace, monkeypatch):
        self.patch_blocked(monkeypatch)
        body = TestUnderwriting().payload()
        body["subject"]["zip_code"] = "32501"
        response = client.post(
            "/deal-intelligence/underwrite", json=body, headers=auth(workspace["key"])
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["valuation"]["arv"] > 0
        assert result["valuation"]["appreciation"]["measured"] is False
        assert result["market"]["errors"]

    def test_an_assumed_appreciation_rate_is_warned_about(self, workspace, monkeypatch):
        self.patch_blocked(monkeypatch)
        body = TestUnderwriting().payload()
        body["subject"]["zip_code"] = "32501"
        response = client.post(
            "/deal-intelligence/underwrite", json=body, headers=auth(workspace["key"])
        )
        warnings = " ".join(response.json()["valuation"]["warnings"])
        assert "assumed appreciation rate" in warnings

    def test_status_declares_the_comparable_sales_gap(self, workspace):
        body = client.get("/deal-intelligence/status", headers=auth(workspace["key"])).json()
        assert body["capabilities"]["public_market_data"] is True
        gaps = {gap["gap"] for gap in body["data_gaps"]}
        assert "individual comparable sales" in gaps

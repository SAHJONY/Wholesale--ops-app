import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient

from api.index import app
from app import security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization, WorkspaceEntity
from app.database import SessionLocal
from app.intelligence_ingest import ingest_provider_facts
from app.models import Buyer, Lead, Property

client = TestClient(app)


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()


def _workspace():
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        org = Organization(name=f"MS Org {suffix}", slug=f"ms-org-{suffix}")
        user = AppUser(email=f"ms-{suffix}@example.com", name="Ops")
        db.add_all([org, user]); db.flush()
        db.add_all([
            Membership(organization_id=org.id, user_id=user.id, role="manager"),
            ApiCredential(organization_id=org.id, user_id=user.id, name="key",
                          key_prefix=key[:18], key_hash=_hash_key(key)),
        ])
        db.commit()
        return key, org.id
    finally:
        db.close()


def _buyer(org_id, zips, **kw):
    db = SessionLocal()
    try:
        b = Buyer(name=kw.pop("name", "Cash Buyer"), phone="+15555550001", zip_codes=zips, **kw)
        db.add(b); db.flush()
        db.add(WorkspaceEntity(organization_id=org_id, entity_type="buyer", entity_id=b.id))
        db.commit(); return b.id
    finally:
        db.close()


def _property(org_id, zip_code, state="FL", city="Pensacola", **kw):
    db = SessionLocal()
    try:
        lead = Lead(seller_name="Seller", phone="+15555550000")
        db.add(lead); db.flush()
        p = Property(lead_id=lead.id, address=f"{uuid.uuid4().hex[:5]} Main St",
                     city=city, state=state, zip_code=zip_code, **kw)
        db.add(p); db.flush()
        db.add(WorkspaceEntity(organization_id=org_id, entity_type="property", entity_id=p.id))
        db.commit(); return p.id
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_criteria_states_the_missing_evidence_rule():
    key, _ = _workspace()
    body = client.get("/market-selection/criteria", headers=_auth(key)).json()
    assert body["market_key"] == "zip_code"
    assert {d["id"] for d in body["dimensions"]} == {
        "cash_buyer_depth", "buyer_liquidity", "buy_box_fit", "distress_supply", "verified_coverage"}
    assert "not scored as zero" in body["scoring_rule"]


def test_market_with_buyers_scores_on_buyer_dimensions():
    key, org = _workspace()
    _buyer(org, ["32501"], proof_of_funds_verified=True, reliability_score=90,
           response_rate=80, closing_days=10, min_price=50000, max_price=400000)
    body = client.post("/market-selection/rank", headers=_auth(key), json={}).json()
    market = next(m for m in body["markets"] if m["zip_code"] == "32501")
    assert market["cash_buyers"] == 1
    assert market["scores"]["cash_buyer_depth"] > 0
    assert market["scores"]["buyer_liquidity"] > 0


def test_unevidenced_dimensions_are_reported_not_zeroed():
    """A market with only buyer data must not be scored as if distress and
    verification had been measured and found absent."""
    key, org = _workspace()
    _buyer(org, ["32502"], reliability_score=70, response_rate=60, closing_days=14)
    body = client.post("/market-selection/rank", headers=_auth(key), json={}).json()
    market = next(m for m in body["markets"] if m["zip_code"] == "32502")
    missing = {m["id"] for m in market["missing_dimensions"]}
    assert "distress_supply" in missing
    assert "distress_supply" not in market["scores"]
    assert market["evidence_coverage_percent"] < 100
    assert market["confidence"] in {"low", "moderate"}


def test_more_and_better_buyers_rank_higher():
    key, org = _workspace()
    for i in range(4):
        _buyer(org, ["33101"], proof_of_funds_verified=True, reliability_score=95,
               response_rate=90, closing_days=7, name=f"Deep {i}")
    _buyer(org, ["33102"], proof_of_funds_verified=False, reliability_score=30,
           response_rate=10, closing_days=45, name="Thin")
    body = client.post("/market-selection/rank", headers=_auth(key),
                       json={"states": [], "weights": {"cash_buyer_depth": 1.0}}).json()
    ordered = [m["zip_code"] for m in body["markets"] if m["zip_code"] in {"33101", "33102"}]
    assert ordered.index("33101") < ordered.index("33102")


def test_verified_coverage_reflects_verified_properties():
    key, org = _workspace()
    verified_id = _property(org, "32504", latitude=30.42, longitude=-87.21)
    _property(org, "32504")
    db = SessionLocal()
    try:
        ingest_provider_facts(
            db, org, "property", verified_id, "census_geocoder",
            {"latitude": 30.42, "longitude": -87.21, "normalized_address": "1 Main St"},
            confidence=92, verification_status="verified",
        )
        db.commit()
    finally:
        db.close()
    body = client.get("/market-selection/market/32504", headers=_auth(key)).json()
    assert body["properties"] == 2
    assert body["verified_properties"] == 1
    assert body["scores"]["verified_coverage"] == 50.0


def test_state_and_buyer_filters_apply():
    key, org = _workspace()
    _buyer(org, ["30301"])
    _property(org, "30301", state="GA", city="Atlanta")
    _property(org, "32505", state="FL")
    body = client.post("/market-selection/rank", headers=_auth(key),
                       json={"states": ["GA"], "min_cash_buyers": 1}).json()
    zips = {m["zip_code"] for m in body["markets"]}
    assert "30301" in zips and "32505" not in zips


def test_texas_properties_are_excluded():
    key, org = _workspace()
    _property(org, "77002", state="TX", city="Houston")
    body = client.post("/market-selection/rank", headers=_auth(key), json={}).json()
    assert "77002" not in {m["zip_code"] for m in body["markets"]}


def test_unknown_weight_is_rejected():
    key, _ = _workspace()
    r = client.post("/market-selection/rank", headers=_auth(key), json={"weights": {"vibes": 1}})
    assert r.status_code == 422


def test_another_workspace_buyers_are_not_counted():
    _, other = _workspace()
    _buyer(other, ["44101"], reliability_score=99)
    key, _ = _workspace()
    body = client.post("/market-selection/rank", headers=_auth(key), json={}).json()
    assert "44101" not in {m["zip_code"] for m in body["markets"]}


def test_better_evidenced_markets_rank_above_thinly_measured_ones():
    """A weighted mean over two dimensions is not comparable to one over four.

    Without tiering, a market measured only on the dimensions it happens to
    score well on floats above a better-evidenced market with more buyers.
    """
    key, org = _workspace()
    # Thin: one buyer, nothing else measurable, but excellent liquidity.
    _buyer(org, ["59001"], proof_of_funds_verified=True, reliability_score=99,
           response_rate=99, closing_days=5, name="Thin but fast")
    # Well-evidenced: more buyers plus properties, so more dimensions score,
    # including a verified_coverage of 0 that drags the mean down.
    for i in range(3):
        _buyer(org, ["59002"], proof_of_funds_verified=True, reliability_score=90,
               response_rate=85, closing_days=10, name=f"Deep {i}")
    _property(org, "59002", state="MT", city="Billings", asking_price=150000, repairs=20000)

    body = client.post("/market-selection/rank", headers=_auth(key),
                       json={"min_cash_buyers": 1}).json()
    ordered = [m["zip_code"] for m in body["markets"] if m["zip_code"] in {"59001", "59002"}]
    thin = next(m for m in body["markets"] if m["zip_code"] == "59001")
    deep = next(m for m in body["markets"] if m["zip_code"] == "59002")

    assert deep["evidence_coverage_percent"] > thin["evidence_coverage_percent"]
    assert ordered.index("59002") < ordered.index("59001"), (
        "better-evidenced market must not rank below a thinly measured one"
    )

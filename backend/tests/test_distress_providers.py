import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from fastapi.testclient import TestClient

from api.index import app
from app import distress_providers, security_middleware
from app.auth import _hash_key, _new_key
from app.auth_models import ApiCredential, AppUser, Membership, Organization
from app.database import SessionLocal

client = TestClient(app)

MANAGED_ENV = [
    "DISTRESS_TAX_DELINQUENCY_ENABLED",
    "DISTRESS_TAX_DELINQUENCY_ENDPOINT",
    "LISTING_FSBO_ENABLED",
    "LISTING_FSBO_ENDPOINT",
    distress_providers.LICENSE_ATTESTATION_ENV,
]


def setup_function():
    security_middleware._ATTEMPTS.clear()
    security_middleware._BLOCKS.clear()
    for name in MANAGED_ENV:
        os.environ.pop(name, None)


teardown_function = setup_function


def _workspace():
    suffix = uuid.uuid4().hex[:10]
    key = _new_key()
    db = SessionLocal()
    try:
        organization = Organization(name=f"Distress Org {suffix}", slug=f"distress-org-{suffix}")
        user = AppUser(email=f"ops-{suffix}@example.com", name="Ops")
        db.add_all([organization, user])
        db.flush()
        db.add_all([
            Membership(organization_id=organization.id, user_id=user.id, role="manager"),
            ApiCredential(
                organization_id=organization.id, user_id=user.id, name="Ops key",
                key_prefix=key[:18], key_hash=_hash_key(key),
            ),
        ])
        db.commit()
        return key
    finally:
        db.close()


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


def _catalog(key):
    response = client.get("/distress-data/catalog", headers=_auth(key))
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["providers"]}


def test_every_provider_is_disabled_until_configured():
    providers = _catalog(_workspace())
    assert providers, "catalog must list providers"
    for provider_id, item in providers.items():
        assert item["state"] == "disabled", f"{provider_id} must default to disabled"


def test_public_distress_categories_are_covered():
    providers = _catalog(_workspace())
    for expected in (
        "tax_delinquency",
        "code_violation",
        "probate",
        "lis_pendens",
        "foreclosure_sale",
        "demolition_permit",
    ):
        assert expected in providers
        assert providers[expected]["access"] == "public_record"


def test_scraping_is_not_an_available_transport():
    key = _workspace()
    body = client.get("/distress-data/catalog", headers=_auth(key)).json()
    assert body["collection_policy"]["html_scraping_supported"] is False
    assert body["collection_policy"]["access_controls_bypassed"] is False
    for item in body["providers"]:
        assert "scrape" not in " ".join(item["supported_transports"]).lower()


def test_public_record_provider_configures_with_an_endpoint():
    os.environ["DISTRESS_TAX_DELINQUENCY_ENABLED"] = "true"
    os.environ["DISTRESS_TAX_DELINQUENCY_ENDPOINT"] = "https://data.example-county.gov/resource/abcd-1234.json"
    providers = _catalog(_workspace())
    assert providers["tax_delinquency"]["state"] == "configured"


def test_enabling_a_public_provider_without_an_endpoint_reports_the_gap():
    os.environ["DISTRESS_TAX_DELINQUENCY_ENABLED"] = "true"
    providers = _catalog(_workspace())
    assert providers["tax_delinquency"]["state"] == "enabled_missing_endpoint"
    assert "DISTRESS_TAX_DELINQUENCY_ENDPOINT" in providers["tax_delinquency"]["blocker"]


def test_fsbo_is_licensed_and_needs_more_than_an_endpoint():
    """FSBO is not a public record, so an endpoint alone must not unlock it."""
    os.environ["LISTING_FSBO_ENABLED"] = "true"
    os.environ["LISTING_FSBO_ENDPOINT"] = "https://licensed.example.com/fsbo"
    providers = _catalog(_workspace())
    fsbo = providers["fsbo_listing"]
    assert fsbo["access"] == "licensed"
    assert fsbo["license_required"] is True
    assert fsbo["state"] == "blocked_missing_license_attestation"


def test_fsbo_unlocks_only_with_a_recorded_agreement():
    os.environ["LISTING_FSBO_ENABLED"] = "true"
    os.environ["LISTING_FSBO_ENDPOINT"] = "https://licensed.example.com/fsbo"
    os.environ[distress_providers.LICENSE_ATTESTATION_ENV] = "MSA-2026-114"
    providers = _catalog(_workspace())
    assert providers["fsbo_listing"]["state"] == "configured"


def test_fsbo_facts_are_never_claimed_as_verified():
    providers = _catalog(_workspace())
    assert providers["fsbo_listing"]["verification_status"] == "unverified"
    # Seller-stated price must not masquerade as an appraised or recorded value.
    assert "fsbo_asking_price" in providers["fsbo_listing"]["writable_fields"]
    assert "arv" not in providers["fsbo_listing"]["writable_fields"]


def test_probate_stays_below_verified_because_matching_is_inferred():
    providers = _catalog(_workspace())
    assert providers["probate"]["verification_status"] == "partially_verified"


def test_readiness_reports_outstanding_configuration():
    key = _workspace()
    response = client.get("/distress-data/readiness", headers=_auth(key))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is False
    assert body["configured_providers"] == []
    assert "Configure at least one jurisdiction" in body["next_step"]

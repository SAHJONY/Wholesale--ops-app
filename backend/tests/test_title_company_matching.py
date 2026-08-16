from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.title_company_matching import _validate_verified_capabilities, score_title_company
from app.title_company_models import TitleCompanyPartner


def property_row(state="FL", zip_code="33101"):
    return SimpleNamespace(state=state, zip_code=zip_code)


def partner(**overrides):
    values = {
        "id": 1,
        "organization_id": 1,
        "name": "Investor Title Co",
        "normalized_name": "investor title co",
        "states": ["FL"],
        "counties": [],
        "zip_codes": [],
        "active": True,
        "assignment_support": "verified",
        "double_close_support": "verified",
        "simultaneous_close_support": "unverified",
        "transactional_funding_coordination": "unverified",
        "remote_closing": "verified",
        "e_signing": "verified",
        "investor_closings_observed": 20,
        "wholesale_closings_observed": 12,
        "avg_title_turnaround_days": 2,
        "avg_closing_days": 10,
        "reliability_score": 90,
        "fee_transparency_score": 90,
        "evidence": [{"source": "title_company_confirmation", "verified_at": "2026-08-16"}],
    }
    values.update(overrides)
    return TitleCompanyPartner(**values)


def test_verified_assignment_partner_is_eligible_and_high_confidence():
    result = score_title_company(partner(), property_row(), "assignment")
    assert result["eligible"] is True
    assert result["evidence_status"] == "verified"
    assert result["score"] >= 80
    assert "assignment_support_verified" in result["reasons"]


def test_claimed_assignment_support_never_becomes_eligible():
    result = score_title_company(partner(assignment_support="claimed"), property_row(), "assignment")
    assert result["eligible"] is False
    assert result["evidence_status"] == "needs_verification"
    assert "assignment_support_claimed_not_verified" in result["reasons"]


def test_state_mismatch_is_ineligible_even_with_verified_assignment_support():
    result = score_title_company(partner(states=["GA"]), property_row(state="FL"), "assignment")
    assert result["eligible"] is False
    assert result["evidence_status"] == "jurisdiction_mismatch"
    assert "state_not_supported" in result["reasons"]


def test_verified_capability_requires_evidence():
    with pytest.raises(HTTPException) as exc:
        _validate_verified_capabilities({"assignment_support": "verified", "evidence": []})
    assert exc.value.status_code == 422


def test_claimed_capability_can_enter_registry_for_later_verification():
    _validate_verified_capabilities({"assignment_support": "claimed", "evidence": []})

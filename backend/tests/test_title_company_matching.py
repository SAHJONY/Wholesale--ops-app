from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.title_company_matching import (
    _apply_closing_outcome,
    _validate_verified_capabilities,
    score_title_company,
)
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


def test_closed_assignment_outcome_teaches_track_record_and_capability():
    row = partner(
        assignment_support="claimed",
        investor_closings_observed=2,
        wholesale_closings_observed=1,
        avg_title_turnaround_days=4,
        avg_closing_days=12,
        reliability_score=70,
        fee_transparency_score=70,
        evidence=[],
    )
    result = _apply_closing_outcome(row, {
        "deal_id": 99,
        "outcome": "closed",
        "strategy": "assignment",
        "title_turnaround_days": 2,
        "closing_days": 9,
        "fee_quote_accurate": True,
        "structure_completed_as_reported": True,
    })
    assert result == {"outcome": "closed", "strategy": "assignment"}
    assert row.investor_closings_observed == 3
    assert row.wholesale_closings_observed == 2
    assert row.assignment_support == "verified"
    assert row.last_verified_at is not None
    assert row.reliability_score == 72
    assert row.fee_transparency_score == 72
    assert row.avg_title_turnaround_days < 4
    assert row.avg_closing_days < 12
    assert row.evidence[-1]["source"] == "sahjony_closing_outcome"
    assert row.evidence[-1]["deal_id"] == 99


def test_failed_closing_penalizes_reliability_and_inaccurate_fee_quote():
    row = partner(reliability_score=85, fee_transparency_score=80)
    _apply_closing_outcome(row, {
        "deal_id": 100,
        "outcome": "failed",
        "strategy": "assignment",
        "fee_quote_accurate": False,
    })
    assert row.reliability_score == 75
    assert row.fee_transparency_score == 75
    assert row.investor_closings_observed == 20
    assert row.wholesale_closings_observed == 12


def test_closed_outcome_without_structure_confirmation_does_not_verify_claim():
    row = partner(assignment_support="claimed", evidence=[])
    _apply_closing_outcome(row, {
        "deal_id": 101,
        "outcome": "closed",
        "strategy": "assignment",
        "structure_completed_as_reported": False,
    })
    assert row.assignment_support == "claimed"


def test_invalid_outcome_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _apply_closing_outcome(partner(), {"outcome": "maybe", "strategy": "assignment"})
    assert exc.value.status_code == 422

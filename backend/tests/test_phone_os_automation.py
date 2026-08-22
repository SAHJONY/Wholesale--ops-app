from pathlib import Path

from app.phone_os import _score

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent


def test_hot_lead_scoring_is_deterministic():
    result = _score({
        "motivation": "Needs to sell after inheriting the property",
        "timeline_days": 21,
        "condition": "Roof and HVAC need work",
        "seller_price": 145000,
        "needs_human": False,
    })
    assert result["pillars_captured"] == 4
    assert result["motivation_score"] == 100
    assert result["hot_lead"] is True


def test_phone_pipeline_never_dispatches_or_commits_deals():
    source = (BACKEND_DIR / "app/phone_os_pipeline.py").read_text()
    assert "OutboundRequest(" not in source
    assert "_dispatch_bland_call" not in source
    assert "Offer(" not in source
    assert "Contract" not in source
    assert "money_movement_autonomous" not in source
    assert '"autonomous_offer_allowed": False' in source
    assert '"autonomous_contract_allowed": False' in source


def test_automation_only_prepares_acquisition_job_and_followup():
    source = (BACKEND_DIR / "app/phone_os_automation.py").read_text()
    assert "ensure_next_work" in source
    assert '"autonomous_outreach": False' in source
    assert '"autonomous_offers": False' in source
    assert '"autonomous_contracts": False' in source
    assert "seller_claims_unverified" in source


def test_phone_os_page_processes_pending_transcripts():
    source = (REPO_DIR / "frontend/app/owner/phone-os/page.tsx").read_text()
    assert "/phone-os/automation/process-pending" in source
    assert "/phone-os/automation/pipeline" in source
    assert "Process & Refresh" in source

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.acquisition_intake import delete_lead
from app.auth import Principal
from app.auth_models import CrmActivity, WorkspaceEntity
from app.county_queue import create_case
from app.county_queue_models import CountyVerificationCase
from app.database import Base
from app.main import app  # noqa: F401 - registers all model metadata
from app.models import Lead, OpsTask, Property


def _principal() -> Principal:
    return Principal(
        organization_id=7,
        organization_name="Test Acquisitions",
        user_id=11,
        email="owner@example.com",
        name="Owner",
        role="owner",
    )


def _lead(db: Session) -> Lead:
    lead = Lead(
        seller_name="Private Owner",
        phone="+15555550123",
        email="owner@example.com",
        source="public_address_paste",
        status="property_candidate",
    )
    lead.property = Property(
        address="100 Main Street",
        city="Pensacola",
        state="FL",
        zip_code="32501",
    )
    db.add(lead)
    db.flush()
    db.add_all([
        WorkspaceEntity(organization_id=7, entity_type="lead", entity_id=lead.id),
        WorkspaceEntity(organization_id=7, entity_type="property", entity_id=lead.property.id),
        OpsTask(task_type="enrich", status="queued", lead_id=lead.id),
    ])
    db.commit()
    return lead


def test_delete_lead_suppresses_contact_data_and_cancels_work():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lead = _lead(db)
        lead_id = lead.id
        result = delete_lead(lead_id, {"reason": "Duplicate record"}, _principal(), db)

        deleted = db.get(Lead, lead_id)
        assert result["audit_retained"] is True
        assert result["recoverable_from_audit"] is False
        assert deleted.status == "deleted"
        assert deleted.seller_name == "Deleted lead"
        assert deleted.phone == "deleted"
        assert deleted.email is None
        assert db.scalar(select(OpsTask).where(OpsTask.lead_id == lead_id)).status == "cancelled"
        assert db.scalar(select(WorkspaceEntity).where(
            WorkspaceEntity.entity_type == "lead",
            WorkspaceEntity.entity_id == lead_id,
        )) is None
        assert db.scalar(select(CrmActivity).where(
            CrmActivity.lead_id == lead_id,
            CrmActivity.activity_type == "lead_deleted",
        )) is not None


def test_reverse_search_is_research_only_and_confidence_is_capped():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        lead = _lead(db)
        result = create_case(lead.id, {
            "source_type": "reverse_address_research",
            "source_reference": "https://www.cyberbackgroundchecks.com/address/example",
            "confidence": 95,
            "proposed_evidence": {"candidate_owner_name": "Possible Owner"},
        }, _principal(), db)

        case = db.get(CountyVerificationCase, result["case_id"])
        assert case.status == "pending"
        assert case.confidence == 40
        assert case.source_type == "reverse_address_research"
        assert case.proposed_evidence["candidate_owner_name"] == "Possible Owner"

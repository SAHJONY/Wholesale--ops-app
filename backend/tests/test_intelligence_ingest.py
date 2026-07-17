from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.intelligence_ingest import ingest_provider_facts
from app.intelligence_models import CanonicalEntity, IntelligenceConflict, IntelligenceFact


def test_provider_facts_build_canonical_and_conflict():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    first = ingest_provider_facts(
        db, 1, "property", 10, "attom",
        {"owner_name": "Alice Owner", "bedrooms": 3},
        confidence=82, verification_status="partially_verified",
    )
    second = ingest_provider_facts(
        db, 1, "property", 10, "county",
        {"owner_name": "Alice B. Owner", "bedrooms": 3},
        confidence=100, verification_status="verified",
    )
    db.commit()

    canonical = db.scalar(select(CanonicalEntity).where(CanonicalEntity.entity_type == "property", CanonicalEntity.entity_id == 10))
    facts = db.scalars(select(IntelligenceFact).where(IntelligenceFact.entity_type == "property", IntelligenceFact.entity_id == 10)).all()
    conflict = db.scalar(select(IntelligenceConflict).where(IntelligenceConflict.field_name == "owner_name", IntelligenceConflict.status == "open"))

    assert first["facts_written"] == 2
    assert second["facts_written"] == 2
    assert canonical.canonical_data["owner_name"] == "Alice B. Owner"
    assert canonical.canonical_data["bedrooms"] == 3
    assert canonical.verification_status == "disputed"
    assert canonical.conflict_count == 1
    assert len(facts) == 4
    assert conflict is not None
    assert conflict.severity == "high"
    assert len(conflict.competing_values) == 2

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.event_bus import emit_event, ensure_default_subscriptions, process_events
from app.event_models import BusinessEvent, EventDelivery, EventSubscription
from app.models import OpsTask


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_emit_event_is_idempotent_by_event_key():
    db = session()
    first = emit_event(db, 1, "ContractSigned", "deal", 7, event_key="contract:7")
    second = emit_event(db, 1, "ContractSigned", "deal", 7, event_key="contract:7")
    db.commit()
    assert first.id == second.id
    assert db.query(BusinessEvent).count() == 1


def test_default_subscriptions_are_idempotent():
    db = session()
    assert ensure_default_subscriptions(db, 1) > 0
    db.commit()
    count = db.query(EventSubscription).count()
    assert ensure_default_subscriptions(db, 1) == 0
    db.commit()
    assert db.query(EventSubscription).count() == count


def test_processing_creates_one_delivery_and_task():
    db = session()
    emit_event(db, 1, "ContractSigned", "deal", 9, event_key="contract:9")
    db.commit()
    result = process_events(db, 1, 50)
    assert result["completed"] == 1
    assert db.query(EventDelivery).count() == 1
    assert db.query(OpsTask).count() == 1
    event = db.scalar(select(BusinessEvent).where(BusinessEvent.event_key == "contract:9"))
    assert event.status == "completed"


def test_completed_event_is_not_processed_twice():
    db = session()
    emit_event(db, 1, "BuyerSelected", "deal", 11, event_key="buyer:11")
    db.commit()
    process_events(db, 1, 50)
    process_events(db, 1, 50)
    assert db.query(EventDelivery).count() == 1
    assert db.query(OpsTask).count() == 1

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .event_models import BusinessEvent, EventDelivery, EventSubscription
from .models import OpsTask

DEFAULT_SUBSCRIPTIONS = [
    ("acquisition-agent", "LeadCreated", "queue_lead_enrichment"),
    ("underwriting-agent", "LeadEnriched", "queue_underwriting"),
    ("executive-agent", "LeadQualified", "queue_executive_review"),
    ("transaction-agent", "ContractSigned", "queue_closing_initialization"),
    ("disposition-agent", "BuyerMatched", "queue_disposition_review"),
    ("transaction-agent", "BuyerSelected", "queue_funding_verification"),
    ("finance-agent", "ClosingCompleted", "queue_revenue_recognition"),
    ("learning-agent", "RevenueRecognized", "queue_learning_update"),
]


def emit_event(db: Session, organization_id: int, event_type: str, aggregate_type: str,
               aggregate_id: int | None, payload: dict | None = None, *, source: str = "application",
               event_key: str | None = None, correlation_id: str | None = None,
               causation_id: str | None = None, metadata: dict | None = None) -> BusinessEvent:
    key = event_key or f"{organization_id}:{event_type}:{aggregate_type}:{aggregate_id}:{secrets.token_hex(8)}"
    existing = db.scalar(select(BusinessEvent).where(BusinessEvent.event_key == key))
    if existing:
        return existing
    event = BusinessEvent(
        organization_id=organization_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_key=key,
        correlation_id=correlation_id or secrets.token_hex(16),
        causation_id=causation_id,
        source=source,
        payload=payload or {},
        metadata_json=metadata or {},
    )
    db.add(event)
    db.flush()
    return event


def ensure_default_subscriptions(db: Session, organization_id: int) -> int:
    created = 0
    for subscriber, event_type, handler in DEFAULT_SUBSCRIPTIONS:
        existing = db.scalar(select(EventSubscription).where(
            EventSubscription.organization_id == organization_id,
            EventSubscription.subscriber_name == subscriber,
            EventSubscription.event_type == event_type,
        ))
        if not existing:
            db.add(EventSubscription(
                organization_id=organization_id,
                subscriber_name=subscriber,
                event_type=event_type,
                handler_name=handler,
            ))
            created += 1
    db.flush()
    return created


def _dispatch_handler(db: Session, event: BusinessEvent, subscription: EventSubscription) -> dict:
    task_type = subscription.handler_name
    payload = {
        "event_id": event.id,
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "correlation_id": event.correlation_id,
        **(event.payload or {}),
    }
    task = OpsTask(
        task_type=task_type,
        status="queued",
        priority=int((subscription.configuration or {}).get("priority", 70)),
        lead_id=event.aggregate_id if event.aggregate_type == "lead" else None,
        payload=payload,
        requires_approval=bool((subscription.configuration or {}).get("requires_approval", False)),
    )
    db.add(task)
    db.flush()
    return {"task_id": task.id, "task_type": task.task_type}


def process_events(db: Session, organization_id: int, limit: int = 50) -> dict:
    ensure_default_subscriptions(db, organization_id)
    now = datetime.utcnow()
    events = db.scalars(select(BusinessEvent).where(
        BusinessEvent.organization_id == organization_id,
        BusinessEvent.status.in_(["pending", "retry"]),
        BusinessEvent.available_at <= now,
    ).order_by(BusinessEvent.created_at).limit(max(1, min(limit, 200)))).all()
    processed = completed = failed = 0
    for event in events:
        event.status = "processing"
        event.published_at = event.published_at or now
        event.attempts += 1
        subscriptions = db.scalars(select(EventSubscription).where(
            EventSubscription.organization_id == organization_id,
            EventSubscription.event_type == event.event_type,
            EventSubscription.is_active.is_(True),
        )).all()
        if not subscriptions:
            event.status = "completed"
            event.completed_at = now
            completed += 1
            processed += 1
            continue
        event_failed = False
        for sub in subscriptions:
            delivery = db.scalar(select(EventDelivery).where(
                EventDelivery.event_id == event.id,
                EventDelivery.subscription_id == sub.id,
            ))
            if delivery and delivery.status == "completed":
                continue
            if not delivery:
                delivery = EventDelivery(
                    organization_id=organization_id,
                    event_id=event.id,
                    subscription_id=sub.id,
                    subscriber_name=sub.subscriber_name,
                )
                db.add(delivery)
                db.flush()
            delivery.status = "processing"
            delivery.started_at = now
            delivery.attempts += 1
            try:
                delivery.result = _dispatch_handler(db, event, sub)
                delivery.status = "completed"
                delivery.completed_at = datetime.utcnow()
                delivery.last_error = None
            except Exception as exc:
                delivery.last_error = f"{type(exc).__name__}: {exc}"
                if delivery.attempts >= sub.max_attempts:
                    delivery.status = "dead_letter"
                    delivery.failed_at = datetime.utcnow()
                else:
                    delivery.status = "retry"
                    delivery.available_at = datetime.utcnow() + timedelta(minutes=min(60, 2 ** delivery.attempts))
                event_failed = True
        if event_failed:
            event.status = "retry" if event.attempts < 5 else "dead_letter"
            event.available_at = datetime.utcnow() + timedelta(minutes=min(60, 2 ** event.attempts))
            event.failed_at = datetime.utcnow() if event.status == "dead_letter" else None
            failed += 1
        else:
            event.status = "completed"
            event.completed_at = datetime.utcnow()
            event.last_error = None
            completed += 1
        processed += 1
    db.commit()
    return {"processed": processed, "completed": completed, "failed": failed}

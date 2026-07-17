from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .database import get_db
from .event_bus import emit_event, ensure_default_subscriptions, process_events
from .event_models import BusinessEvent, EventDelivery, EventSubscription

router = APIRouter(prefix="/event-core", tags=["event-driven core"])

ALLOWED_MANUAL_EVENTS = {
    "LeadCreated", "LeadEnriched", "LeadQualified", "OfferPrepared", "OfferAccepted",
    "ContractSigned", "BuyerMatched", "BuyerSelected", "TitleOrdered",
    "FundingVerified", "ClosingCompleted", "RevenueRecognized",
}


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    ensure_default_subscriptions(db, principal.organization_id)
    db.commit()
    counts = dict(db.execute(select(BusinessEvent.status, func.count(BusinessEvent.id)).where(
        BusinessEvent.organization_id == principal.organization_id
    ).group_by(BusinessEvent.status)).all())
    delivery_counts = dict(db.execute(select(EventDelivery.status, func.count(EventDelivery.id)).where(
        EventDelivery.organization_id == principal.organization_id
    ).group_by(EventDelivery.status)).all())
    events = db.scalars(select(BusinessEvent).where(
        BusinessEvent.organization_id == principal.organization_id
    ).order_by(BusinessEvent.created_at.desc()).limit(100)).all()
    subscriptions = db.scalars(select(EventSubscription).where(
        EventSubscription.organization_id == principal.organization_id
    ).order_by(EventSubscription.subscriber_name, EventSubscription.event_type)).all()
    return {
        "generated_at": datetime.utcnow(),
        "event_counts": counts,
        "delivery_counts": delivery_counts,
        "health": "degraded" if counts.get("dead_letter", 0) or delivery_counts.get("dead_letter", 0) else "healthy",
        "events": [{
            "id": e.id, "event_type": e.event_type, "aggregate_type": e.aggregate_type,
            "aggregate_id": e.aggregate_id, "event_key": e.event_key,
            "correlation_id": e.correlation_id, "source": e.source, "status": e.status,
            "attempts": e.attempts, "last_error": e.last_error, "payload": e.payload,
            "created_at": e.created_at, "completed_at": e.completed_at,
        } for e in events],
        "subscriptions": [{
            "id": s.id, "subscriber_name": s.subscriber_name, "event_type": s.event_type,
            "handler_name": s.handler_name, "is_active": s.is_active,
            "max_attempts": s.max_attempts, "configuration": s.configuration,
        } for s in subscriptions],
    }


@router.post("/emit")
def manual_emit(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    event_type = str(payload.get("event_type") or "").strip()
    if event_type not in ALLOWED_MANUAL_EVENTS:
        raise HTTPException(422, "Unsupported event type")
    aggregate_type = str(payload.get("aggregate_type") or "system").strip()
    aggregate_id = payload.get("aggregate_id")
    event = emit_event(
        db, principal.organization_id, event_type, aggregate_type,
        int(aggregate_id) if aggregate_id is not None else None,
        payload=payload.get("payload") or {}, source="manual_owner",
        event_key=str(payload.get("event_key") or "").strip() or None,
        correlation_id=str(payload.get("correlation_id") or "").strip() or None,
        metadata={"emitted_by_user_id": principal.user_id},
    )
    db.commit()
    return {"event_id": event.id, "event_key": event.event_key, "status": event.status}


@router.post("/process")
def process(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    limit = int((payload or {}).get("limit") or 50)
    return process_events(db, principal.organization_id, limit)


@router.post("/events/{event_id}/replay")
def replay(event_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    event = db.scalar(select(BusinessEvent).where(
        BusinessEvent.id == event_id,
        BusinessEvent.organization_id == principal.organization_id,
    ))
    if not event:
        raise HTTPException(404, "Event not found")
    event.status = "retry"
    event.available_at = datetime.utcnow()
    event.failed_at = None
    event.last_error = None
    deliveries = db.scalars(select(EventDelivery).where(
        EventDelivery.event_id == event.id,
        EventDelivery.organization_id == principal.organization_id,
    )).all()
    for delivery in deliveries:
        if delivery.status != "completed":
            delivery.status = "retry"
            delivery.available_at = datetime.utcnow()
            delivery.failed_at = None
            delivery.last_error = None
    db.commit()
    return {"event_id": event.id, "status": event.status, "deliveries_reset": len(deliveries)}


@router.patch("/subscriptions/{subscription_id}")
def update_subscription(subscription_id: int, payload: dict, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    subscription = db.scalar(select(EventSubscription).where(
        EventSubscription.id == subscription_id,
        EventSubscription.organization_id == principal.organization_id,
    ))
    if not subscription:
        raise HTTPException(404, "Subscription not found")
    if "is_active" in payload:
        subscription.is_active = bool(payload["is_active"])
    if "max_attempts" in payload:
        subscription.max_attempts = max(1, min(20, int(payload["max_attempts"])))
    if "configuration" in payload and isinstance(payload["configuration"], dict):
        subscription.configuration = payload["configuration"]
    db.commit()
    return {"subscription_id": subscription.id, "is_active": subscription.is_active, "max_attempts": subscription.max_attempts}

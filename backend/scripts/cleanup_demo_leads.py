"""Soft-delete known demo leads after exact identity and deal-safety checks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Deal, Lead, OpsTask, Property

DEMO_SIGNATURES = {
    1: ("Neon Persistent Lead", "900 Database Test Ave"),
    2: ("Jane Seller", "123 Main St"),
    3: ("Test Seller", "100 Test Ave"),
    4: ("Test Seller", "100 Test Ave"),
    5: ("Test Seller", "100 Test Ave"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply the cleanup; otherwise run a dry check.")
    args = parser.parse_args()
    with SessionLocal() as db:
        matched: list[Lead] = []
        for lead_id, expected in DEMO_SIGNATURES.items():
            lead = db.get(Lead, lead_id)
            actual = (lead.seller_name, lead.property.address) if lead and lead.property else None
            if actual != expected:
                raise SystemExit(f"Aborted: lead #{lead_id} expected {expected!r}, found {actual!r}")
            active_deal = db.scalar(select(Deal).join(Property, Deal.property_id == Property.id).where(
                Property.lead_id == lead_id,
                Deal.stage.not_in(["closed", "dead"]),
            ))
            if active_deal:
                raise SystemExit(f"Aborted: lead #{lead_id} has active deal #{active_deal.id}")
            matched.append(lead)
        print(f"Verified {len(matched)} exact demo leads; SAHJONY lead #6 is outside cleanup scope.")
        if not args.apply:
            print("Dry check only. Run with --apply to soft-delete.")
            return
        now = datetime.now(timezone.utc).isoformat()
        for lead in matched:
            original_name = lead.seller_name
            lead.status = "deleted"
            lead.seller_name = "Deleted lead"
            lead.phone = "deleted"
            lead.email = None
            lead.notes = f"Soft deleted at {now}. Reason: confirmed demo/test cleanup ({original_name})"
            for task in db.scalars(select(OpsTask).where(
                OpsTask.lead_id == lead.id,
                OpsTask.status.in_(["queued", "pending"]),
            )).all():
                task.status = "cancelled"
        db.commit()
        print(f"Soft-deleted {len(matched)} demo leads and cancelled their queued work.")


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead, OpsTask
from .task_resolution_engine import ACTIVE_STATUSES, _classify_blocker, _fallback_plan

router = APIRouter(prefix="/self-healing", tags=["self healing"])

HEALABLE = {
    "transient_provider_error",
    "provider_configuration",
    "evidence_gap",
    "data_conflict",
    "unclassified",
}

PROPERTY_STANDARD_VERSION = "2026-08-19-v1"


def _linked_lead_ids(db: Session, organization_id: int):
    return select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )


def _diagnose(task: OpsTask) -> dict[str, Any]:
    blocker = _classify_blocker(task)
    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "blocker": blocker,
        "healability": "automatic_candidate" if blocker in HEALABLE else "guarded",
        "fallback_plan": _fallback_plan(task, blocker),
        "error": task.error,
    }


def _heal_metadata(task: OpsTask, diagnosis: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": "self_healing_engine",
        "diagnosis": diagnosis,
        "healing_policy": {
            "safe_retry": diagnosis["blocker"] == "transient_provider_error",
            "alternate_authorized_source": diagnosis["blocker"] in {"provider_configuration", "evidence_gap", "data_conflict"},
            "human_gate_required": diagnosis["blocker"] == "compliance_or_approval",
            "access_control_bypass_allowed": False,
            "fabricated_success_allowed": False,
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def _ensure_property_standard(db: Session, principal: Principal) -> dict[str, Any]:
    """Ensure every active workspace property has a governed verification packet.

    This is intentionally idempotent. It does not infer an owner, phone, email,
    title fact, ARV, repair scope, or outreach authority. It creates the required
    verification work so no property can silently bypass owner/evidence gates.
    """
    linked = _linked_lead_ids(db, principal.organization_id)
    leads = list(db.scalars(select(Lead).where(
        Lead.id.in_(linked),
        Lead.status.not_in(["deleted", "dead"]),
    ).order_by(Lead.id.asc())).all())

    created_tasks: list[int] = []
    already_standardized: list[int] = []
    skipped_without_property: list[int] = []

    for lead in leads:
        prop = lead.property
        if not prop:
            skipped_without_property.append(lead.id)
            continue

        existing = db.scalar(select(OpsTask).where(
            OpsTask.lead_id == lead.id,
            OpsTask.task_type == "owner_resolution",
            OpsTask.status.in_(["queued", "pending", "in_progress", "blocked", "completed"]),
        ).order_by(OpsTask.id.desc()))
        if existing:
            already_standardized.append(lead.id)
            continue

        address_complete = bool(prop.address and prop.city and prop.state and prop.zip_code)
        task = OpsTask(
            task_type="owner_resolution",
            status="queued" if address_complete else "blocked",
            priority=90 if prop.distress_signals else 80,
            lead_id=lead.id,
            payload={
                "organization_id": principal.organization_id,
                "standard": PROPERTY_STANDARD_VERSION,
                "stage": "property_identity_to_contact_ready",
                "lookup_basis": "property_address" if address_complete else "incomplete_property_identity",
                "property_address": prop.address,
                "city": prop.city,
                "state": prop.state,
                "zip_code": prop.zip_code,
                "required_gates": [
                    "property_identity",
                    "parcel_or_legal_data_when_available",
                    "source_provenance",
                    "official_owner_record_or_address_seed",
                    "contact_cross_verification",
                    "contact_ready",
                    "underwriting_evidence",
                    "buyer_verification",
                    "outreach_compliance",
                ],
                "authorized_automation": [
                    "official_public_record_research",
                    "licensed_provider_enrichment",
                    "task_resolution_engine",
                    "self_healing_engine",
                ],
                "manual_assisted_sources_allowed": True,
                "outreach_allowed": False,
            },
            error=None if address_complete else "Complete property address required before owner resolution",
            requires_approval=False,
        )
        db.add(task)
        db.flush()
        created_tasks.append(task.id)
        db.add(CrmActivity(
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            lead_id=lead.id,
            activity_type="property_verification_standard_applied",
            summary=f"Universal property verification standard applied to lead #{lead.id}",
            metadata_json={
                "standard": PROPERTY_STANDARD_VERSION,
                "task_id": task.id,
                "property_id": prop.id,
                "address_complete": address_complete,
                "outreach_allowed": False,
            },
        ))

    return {
        "standard": PROPERTY_STANDARD_VERSION,
        "properties_seen": len(leads) - len(skipped_without_property),
        "created_owner_resolution_tasks": len(created_tasks),
        "task_ids": created_tasks,
        "already_standardized": len(already_standardized),
        "skipped_without_property": skipped_without_property,
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    linked = _linked_lead_ids(db, principal.organization_id)
    rows = db.scalars(select(OpsTask).where(
        OpsTask.lead_id.in_(linked),
        OpsTask.status.in_(ACTIVE_STATUSES),
    ).order_by(OpsTask.priority.desc(), OpsTask.updated_at.asc()).limit(100)).all()
    diagnoses = [_diagnose(row) for row in rows]
    counts: dict[str, int] = {}
    for item in diagnoses:
        counts[item["blocker"]] = counts.get(item["blocker"], 0) + 1
    return {
        "active_tasks": len(rows),
        "blockers": counts,
        "diagnoses": diagnoses,
        "property_standard": PROPERTY_STANDARD_VERSION,
        "policy": "Heal operational failures automatically only through authorized, reversible paths; never bypass compliance or evidence gates.",
    }


@router.post("/enforce-property-standard")
def enforce_property_standard(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    result = _ensure_property_standard(db, principal)
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="property_standard_enforced",
        summary=f"Universal property standard checked across {result['properties_seen']} properties",
        metadata_json=result,
    ))
    db.commit()
    return result


@router.post("/scan")
def scan(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    limit = max(1, min(100, int((payload or {}).get("limit") or 25)))

    # First heal structural gaps: every property must have an owner-resolution
    # verification packet before task-level recovery is evaluated.
    property_standard = _ensure_property_standard(db, principal)

    linked = _linked_lead_ids(db, principal.organization_id)
    rows = db.scalars(select(OpsTask).where(
        OpsTask.lead_id.in_(linked),
        OpsTask.status.in_(ACTIVE_STATUSES),
    ).order_by(OpsTask.priority.desc(), OpsTask.updated_at.asc()).limit(limit)).all()
    results = []
    for task in rows:
        diagnosis = _diagnose(task)
        result = dict(task.result or {})
        result["self_healing"] = _heal_metadata(task, diagnosis)
        task.result = result
        # Never auto-complete here. Healing prepares or updates the recovery path;
        # task_resolution_engine owns execution/proof-of-success.
        if diagnosis["blocker"] == "transient_provider_error" and task.status == "blocked":
            task.status = "pending"
            task.error = "Self-healing marked task retryable through the authorized resolver path"
        task.updated_at = datetime.now(timezone.utc)
        results.append({"task_id": task.id, "status": task.status, "diagnosis": diagnosis})
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="self_healing_scan",
        summary=f"Self-healing evaluated {len(results)} active tasks",
        metadata_json={"evaluated": len(results), "property_standard": property_standard},
    ))
    db.commit()
    return {"evaluated": len(results), "property_standard": property_standard, "results": results}

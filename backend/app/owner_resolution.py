from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead, OpsTask

router = APIRouter(prefix="/owner-resolution", tags=["owner resolution"])

MANUAL_ASSISTED_SOURCES = {
    "truepeoplesearch": {
        "label": "TruePeopleSearch",
        "url": "https://www.truepeoplesearch.com/",
        "mode": "manual_assisted_public_resolver",
    },
    "cyberbackgroundchecks": {
        "label": "CyberBackgroundChecks",
        "url": "https://www.cyberbackgroundchecks.com/",
        "mode": "manual_assisted_public_resolver",
    },
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def _normalize_email(value: Any) -> str:
    value = _clean(value).lower()
    if value and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return value
    return ""


def _assert_workspace_lead(db: Session, principal: Principal, lead_id: int) -> Lead:
    linked = db.scalar(select(WorkspaceEntity).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    lead = db.get(Lead, lead_id)
    if not linked or not lead:
        raise HTTPException(404, "Lead not found in this workspace")
    if not lead.property:
        raise HTTPException(422, "Lead has no property")
    return lead


def _lookup_packet(lead: Lead) -> dict[str, Any]:
    prop = lead.property
    owner_name = _clean(lead.seller_name)
    owner_known = bool(owner_name and owner_name.lower() not in {"unknown owner", "unknown", "n/a"})
    return {
        "lead_id": lead.id,
        "property_id": prop.id,
        "property_address": prop.address,
        "city": prop.city,
        "state": prop.state,
        "zip_code": prop.zip_code,
        "owner_of_record_name": owner_name if owner_known else None,
        "owner_mailing_address": None,
        "identity_status": "owner_name_available" if owner_known else "owner_record_required",
        "lookup_fields": {
            "name": owner_name if owner_known else None,
            "property_address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
        },
        "manual_assisted_resolvers": MANUAL_ASSISTED_SOURCES,
        "next_step": (
            "Verify owner-of-record and mailing address from assessor/recorder evidence before people-search resolution."
            if not owner_known else
            "Use authorized provider enrichment first; if unresolved, research the listed manual-assisted resolvers and submit source-backed evidence."
        ),
        "outreach_allowed": False,
    }


def _evidence_rows(db: Session, principal: Principal, lead_id: int) -> list[CrmActivity]:
    return list(db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.lead_id == lead_id,
        CrmActivity.activity_type == "owner_resolution_evidence",
    ).order_by(CrmActivity.created_at.asc())).all())


def _resolution_summary(rows: list[CrmActivity]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    phone_sources: dict[str, set[str]] = {}
    email_sources: dict[str, set[str]] = {}
    max_identity_confidence = 0.0
    for row in rows:
        meta = row.metadata_json or {}
        source = _clean(meta.get("source_name")).lower()
        phone = _normalize_phone(meta.get("candidate_phone"))
        email = _normalize_email(meta.get("candidate_email"))
        confidence = float(meta.get("identity_match_confidence") or 0)
        max_identity_confidence = max(max_identity_confidence, confidence)
        if phone and source:
            phone_sources.setdefault(phone, set()).add(source)
        if email and source:
            email_sources.setdefault(email, set()).add(source)
        evidence.append({
            "activity_id": row.id,
            "source_name": meta.get("source_name"),
            "source_url": meta.get("source_url"),
            "retrieved_at": meta.get("retrieved_at"),
            "candidate_phone": meta.get("candidate_phone"),
            "candidate_email": meta.get("candidate_email"),
            "identity_match_confidence": confidence,
            "evidence_notes": meta.get("evidence_notes"),
        })

    cross_verified_phones = [phone for phone, sources in phone_sources.items() if len(sources) >= 2]
    cross_verified_emails = [email for email, sources in email_sources.items() if len(sources) >= 2]
    cross_verified = bool(cross_verified_phones or cross_verified_emails)
    contact_ready = cross_verified and max_identity_confidence >= 80
    return {
        "evidence_count": len(evidence),
        "evidence": evidence,
        "cross_verified_phones": cross_verified_phones,
        "cross_verified_emails": cross_verified_emails,
        "max_identity_match_confidence": max_identity_confidence,
        "status": "contact_ready" if contact_ready else ("cross_verified" if cross_verified else ("likely" if evidence else "unverified")),
        "contact_ready": contact_ready,
        "outreach_allowed": False,
        "note": "Contact Ready verifies identity evidence only. It does not establish consent, DNC clearance, or permission for automated outreach.",
    }


@router.get("/leads/{lead_id}/packet")
def owner_resolution_packet(
    lead_id: int,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    lead = _assert_workspace_lead(db, principal, lead_id)
    return {**_lookup_packet(lead), "resolution": _resolution_summary(_evidence_rows(db, principal, lead_id))}


@router.post("/queue-property-candidates")
def queue_property_candidates(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    payload = payload or {}
    limit = max(1, min(int(payload.get("limit") or 100), 500))
    lead_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    leads = list(db.scalars(select(Lead).where(
        Lead.id.in_(lead_ids),
        Lead.status == "property_candidate",
    ).order_by(Lead.created_at.asc()).limit(limit)).all()) if lead_ids else []

    queued = skipped = 0
    tasks: list[int] = []
    for lead in leads:
        existing = db.scalar(select(OpsTask).where(
            OpsTask.lead_id == lead.id,
            OpsTask.task_type == "owner_resolution",
            OpsTask.status.in_(["queued", "pending", "in_progress"]),
        ))
        if existing:
            skipped += 1
            continue
        task = OpsTask(
            task_type="owner_resolution",
            status="queued",
            priority=85 if (lead.property and lead.property.distress_signals) else 70,
            lead_id=lead.id,
            payload={
                "organization_id": principal.organization_id,
                "lookup_packet": _lookup_packet(lead),
                "authorized_automation": ["county_owner_verification", "licensed_provider_enrichment"],
                "manual_assisted_sources": list(MANUAL_ASSISTED_SOURCES),
                "outreach_allowed": False,
            },
            requires_approval=False,
        )
        db.add(task)
        db.flush()
        tasks.append(task.id)
        queued += 1
    db.commit()
    return {
        "status": "queued",
        "candidates_seen": len(leads),
        "queued": queued,
        "skipped_existing": skipped,
        "task_ids": tasks,
        "outreach_allowed": False,
    }


@router.post("/leads/{lead_id}/evidence")
def add_manual_resolution_evidence(
    lead_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    lead = _assert_workspace_lead(db, principal, lead_id)
    source_name = _clean(payload.get("source_name")).lower()
    if source_name not in MANUAL_ASSISTED_SOURCES:
        raise HTTPException(422, "source_name must be truepeoplesearch or cyberbackgroundchecks")
    source_url = _clean(payload.get("source_url"))
    if not source_url.startswith("https://"):
        raise HTTPException(422, "source_url must be HTTPS")
    phone = _normalize_phone(payload.get("candidate_phone"))
    email = _normalize_email(payload.get("candidate_email"))
    if not phone and not email:
        raise HTTPException(422, "Provide a valid candidate_phone and/or candidate_email")
    confidence = float(payload.get("identity_match_confidence") or 0)
    if confidence < 0 or confidence > 100:
        raise HTTPException(422, "identity_match_confidence must be between 0 and 100")
    notes = _clean(payload.get("evidence_notes"))
    if len(notes) < 8:
        raise HTTPException(422, "evidence_notes must explain the identity match")

    now = datetime.now(timezone.utc).isoformat()
    activity = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="owner_resolution_evidence",
        summary=f"Owner/contact candidate recorded from {MANUAL_ASSISTED_SOURCES[source_name]['label']}",
        metadata_json={
            "source_name": source_name,
            "source_url": source_url,
            "source_mode": MANUAL_ASSISTED_SOURCES[source_name]["mode"],
            "retrieved_at": _clean(payload.get("retrieved_at")) or now,
            "owner_of_record_name": _clean(payload.get("owner_of_record_name")) or _clean(lead.seller_name),
            "owner_mailing_address": _clean(payload.get("owner_mailing_address")) or None,
            "candidate_phone": phone or None,
            "candidate_email": email or None,
            "identity_match_confidence": confidence,
            "evidence_notes": notes,
            "automated_scraping_used": False,
            "outreach_allowed": False,
        },
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {
        "lead_id": lead.id,
        "activity_id": activity.id,
        "resolution": _resolution_summary(_evidence_rows(db, principal, lead_id)),
        "applied_to_lead": False,
    }


@router.post("/leads/{lead_id}/apply-contact-ready")
def apply_contact_ready(
    lead_id: int,
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    lead = _assert_workspace_lead(db, principal, lead_id)
    summary = _resolution_summary(_evidence_rows(db, principal, lead_id))
    if not summary["contact_ready"]:
        raise HTTPException(409, "Contact evidence is not cross-verified at the required confidence")
    payload = payload or {}
    applied: dict[str, str] = {}
    if summary["cross_verified_phones"] and (not lead.phone or lead.phone in {"unknown", "deleted"} or bool(payload.get("replace_phone"))):
        lead.phone = summary["cross_verified_phones"][0]
        applied["phone"] = lead.phone
    if summary["cross_verified_emails"] and (not lead.email or bool(payload.get("replace_email"))):
        lead.email = summary["cross_verified_emails"][0]
        applied["email"] = lead.email
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="owner_resolution_applied",
        summary=f"Cross-verified owner contact applied; fields={','.join(applied) or 'none'}",
        metadata_json={
            "applied_fields": applied,
            "resolution_status": summary["status"],
            "outreach_allowed": False,
            "requires_downstream_compliance_review": True,
        },
    ))
    db.commit()
    return {
        "lead_id": lead.id,
        "status": summary["status"],
        "applied": applied,
        "outreach_allowed": False,
        "next_gate": "DNC/TCPA/state/compliance review before any automated SMS or call.",
    }

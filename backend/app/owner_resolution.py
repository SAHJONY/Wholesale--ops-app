from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .county_source_registry import VERIFICATION_SOURCE_KINDS, source_authority
from .database import get_db
from .models import Lead, OpsTask

router = APIRouter(prefix="/owner-resolution", tags=["owner resolution"])

MANUAL_ASSISTED_SOURCES = {
    "truepeoplesearch": {"label": "TruePeopleSearch", "url": "https://www.truepeoplesearch.com/", "mode": "manual_assisted_public_resolver"},
    "cyberbackgroundchecks": {"label": "CyberBackgroundChecks", "url": "https://www.cyberbackgroundchecks.com/", "mode": "manual_assisted_public_resolver"},
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
    return value if value and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else ""


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


def _activity_rows(db: Session, principal: Principal, lead_id: int, activity_type: str) -> list[CrmActivity]:
    return list(db.scalars(select(CrmActivity).where(
        CrmActivity.organization_id == principal.organization_id,
        CrmActivity.lead_id == lead_id,
        CrmActivity.activity_type == activity_type,
    ).order_by(CrmActivity.created_at.asc())).all())


def _owner_record_summary(rows: list[CrmActivity]) -> dict[str, Any]:
    evidence = []
    for row in rows:
        meta = row.metadata_json or {}
        evidence.append({
            "activity_id": row.id,
            "source_kind": meta.get("source_kind"),
            "source_url": meta.get("source_url"),
            "source_authority": meta.get("source_authority"),
            "owner_of_record_name": meta.get("owner_of_record_name"),
            "owner_mailing_address": meta.get("owner_mailing_address"),
            "parcel_id": meta.get("parcel_id"),
            "recorded_document": meta.get("recorded_document"),
            "retrieved_at": meta.get("retrieved_at"),
            "evidence_notes": meta.get("evidence_notes"),
        })
    latest = evidence[-1] if evidence else None
    verified = bool(latest and latest.get("owner_of_record_name") and latest.get("source_kind") in VERIFICATION_SOURCE_KINDS)
    return {
        "verified": verified,
        "status": "verified" if verified else "unavailable_or_unverified",
        "evidence_count": len(evidence),
        "evidence": evidence,
        "owner_of_record_name": latest.get("owner_of_record_name") if latest else None,
        "owner_mailing_address": latest.get("owner_mailing_address") if latest else None,
        "source_url": latest.get("source_url") if latest else None,
    }


def _resolution_summary(rows: list[CrmActivity], owner_verified: bool, address_seeded: bool) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    phone_sources: dict[str, set[str]] = {}
    email_sources: dict[str, set[str]] = {}
    max_confidence = 0.0
    for row in rows:
        meta = row.metadata_json or {}
        source = _clean(meta.get("source_name")).lower()
        phone = _normalize_phone(meta.get("candidate_phone"))
        email = _normalize_email(meta.get("candidate_email"))
        confidence = float(meta.get("identity_match_confidence") or 0)
        max_confidence = max(max_confidence, confidence)
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
            "lookup_basis": meta.get("lookup_basis"),
        })
    phones = [p for p, sources in phone_sources.items() if len(sources) >= 2]
    emails = [e for e, sources in email_sources.items() if len(sources) >= 2]
    cross_verified = bool(phones or emails)
    required_confidence = 80 if owner_verified else 90
    contact_ready = bool((owner_verified or address_seeded) and cross_verified and max_confidence >= required_confidence)
    status = "contact_ready" if contact_ready else ("cross_verified" if cross_verified else ("likely" if evidence else "unverified"))
    basis = "owner_of_record" if owner_verified else "property_address"
    return {
        "evidence_count": len(evidence),
        "evidence": evidence,
        "cross_verified_phones": phones,
        "cross_verified_emails": emails,
        "max_identity_match_confidence": max_confidence,
        "required_identity_confidence": required_confidence,
        "lookup_basis": basis,
        "status": status,
        "contact_ready": contact_ready,
        "outreach_allowed": False,
        "note": (
            "Owner-of-record is verified; two independent matching contact sources plus at least 80% identity confidence are required."
            if owner_verified else
            "Owner-of-record is unavailable, so the property address is the lookup seed. Two independent matching contact sources plus at least 90% identity confidence are required before Contact Ready."
        ),
    }


def _packet(db: Session, principal: Principal, lead: Lead) -> dict[str, Any]:
    prop = lead.property
    owner_record = _owner_record_summary(_activity_rows(db, principal, lead.id, "owner_record_evidence"))
    lead_name = _clean(lead.seller_name)
    owner_name = owner_record.get("owner_of_record_name") or (lead_name if lead_name.lower() not in {"", "unknown", "unknown owner", "n/a"} else None)
    address_seeded = bool(_clean(prop.address) and _clean(prop.city) and _clean(prop.state) and _clean(prop.zip_code))
    resolution = _resolution_summary(
        _activity_rows(db, principal, lead.id, "owner_resolution_evidence"),
        bool(owner_record["verified"]),
        address_seeded,
    )
    lookup_basis = "owner_of_record" if owner_record["verified"] else "property_address"
    return {
        "lead_id": lead.id,
        "property_id": prop.id,
        "property_address": prop.address,
        "city": prop.city,
        "state": prop.state,
        "zip_code": prop.zip_code,
        "owner_of_record_name": owner_record.get("owner_of_record_name"),
        "owner_mailing_address": owner_record.get("owner_mailing_address"),
        "identity_status": "owner_record_verified" if owner_record["verified"] else "address_seed_resolution",
        "owner_record": owner_record,
        "lookup_basis": lookup_basis,
        "lookup_fields": {
            "name": owner_name,
            "property_address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
        },
        "manual_assisted_resolvers": MANUAL_ASSISTED_SOURCES if address_seeded else {},
        "people_search_unlocked": address_seeded,
        "next_step": (
            "Use licensed enrichment or manual-assisted people-search resolvers with the verified owner name and property address."
            if owner_record["verified"] else
            "Owner-of-record is unavailable. Search by the full property address first, identify resident/owner candidates, then cross-verify the same contact across two independent sources."
        ),
        "resolution": resolution,
        "outreach_allowed": False,
    }


@router.get("/leads/{lead_id}/packet")
def owner_resolution_packet(
    lead_id: int,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    return _packet(db, principal, _assert_workspace_lead(db, principal, lead_id))


@router.post("/leads/{lead_id}/owner-record-evidence")
def add_owner_record_evidence(
    lead_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    lead = _assert_workspace_lead(db, principal, lead_id)
    source_kind = _clean(payload.get("source_kind")).lower()
    if source_kind not in VERIFICATION_SOURCE_KINDS:
        raise HTTPException(422, f"source_kind must be one of: {', '.join(VERIFICATION_SOURCE_KINDS)}")
    source_url = _clean(payload.get("source_url"))
    owner_name = _clean(payload.get("owner_of_record_name"))
    notes = _clean(payload.get("evidence_notes"))
    if not source_url.startswith("https://") or not owner_name or len(notes) < 8:
        raise HTTPException(422, "HTTPS source_url, owner_of_record_name and evidence_notes are required")
    authority = source_authority(source_url)
    activity = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="owner_record_evidence",
        summary=f"Owner-of-record verified from {source_kind}",
        metadata_json={
            "source_kind": source_kind,
            "source_url": source_url,
            "source_authority": authority,
            "owner_of_record_name": owner_name,
            "owner_mailing_address": _clean(payload.get("owner_mailing_address")) or None,
            "parcel_id": _clean(payload.get("parcel_id")) or None,
            "recorded_document": _clean(payload.get("recorded_document")) or None,
            "retrieved_at": _clean(payload.get("retrieved_at")) or datetime.now(timezone.utc).isoformat(),
            "evidence_notes": notes,
            "outreach_allowed": False,
        },
    )
    db.add(activity)
    if not lead_name_is_known(lead.seller_name):
        lead.seller_name = owner_name
    db.commit()
    return _packet(db, principal, lead)


def lead_name_is_known(value: Any) -> bool:
    return _clean(value).lower() not in {"", "unknown", "unknown owner", "n/a"}


@router.post("/queue-property-candidates")
def queue_property_candidates(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    limit = max(1, min(int((payload or {}).get("limit") or 100), 500))
    lead_ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    leads = list(db.scalars(select(Lead).where(
        Lead.id.in_(lead_ids),
        Lead.status == "property_candidate",
    ).order_by(Lead.created_at.asc()).limit(limit)).all()) if lead_ids else []
    queued = skipped = 0
    tasks = []
    for lead in leads:
        existing = db.scalar(select(OpsTask).where(
            OpsTask.lead_id == lead.id,
            OpsTask.task_type == "owner_resolution",
            OpsTask.status.in_(["queued", "pending", "in_progress"]),
        ))
        if existing:
            skipped += 1
            continue
        packet = _packet(db, principal, lead)
        task = OpsTask(
            task_type="owner_resolution",
            status="queued",
            priority=85 if lead.property and lead.property.distress_signals else 70,
            lead_id=lead.id,
            payload={
                "organization_id": principal.organization_id,
                "stage": "contact_resolution",
                "lookup_basis": packet["lookup_basis"],
                "lookup_fields": packet["lookup_fields"],
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
    packet = _packet(db, principal, lead)
    if not packet["people_search_unlocked"]:
        raise HTTPException(409, "A complete property address is required for address-seeded resolution")
    source_name = _clean(payload.get("source_name")).lower()
    if source_name not in MANUAL_ASSISTED_SOURCES:
        raise HTTPException(422, "source_name must be truepeoplesearch or cyberbackgroundchecks")
    source_url = _clean(payload.get("source_url"))
    phone = _normalize_phone(payload.get("candidate_phone"))
    email = _normalize_email(payload.get("candidate_email"))
    confidence = float(payload.get("identity_match_confidence") or 0)
    notes = _clean(payload.get("evidence_notes"))
    if not source_url.startswith("https://") or (not phone and not email) or not 0 <= confidence <= 100 or len(notes) < 8:
        raise HTTPException(422, "Valid source URL, contact candidate, confidence and evidence notes are required")
    lookup_basis = packet["lookup_basis"]
    activity = CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=lead.id,
        activity_type="owner_resolution_evidence",
        summary=f"Contact candidate recorded from {MANUAL_ASSISTED_SOURCES[source_name]['label']} using {lookup_basis}",
        metadata_json={
            "source_name": source_name,
            "source_url": source_url,
            "source_mode": MANUAL_ASSISTED_SOURCES[source_name]["mode"],
            "retrieved_at": _clean(payload.get("retrieved_at")) or datetime.now(timezone.utc).isoformat(),
            "lookup_basis": lookup_basis,
            "lookup_property_address": packet["property_address"],
            "owner_of_record_name": packet["owner_of_record_name"],
            "owner_mailing_address": packet["owner_mailing_address"],
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
        "resolution": _packet(db, principal, lead)["resolution"],
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
    packet = _packet(db, principal, lead)
    summary = packet["resolution"]
    if not summary["contact_ready"]:
        raise HTTPException(409, "Contact evidence is not cross-verified at the required confidence")
    payload = payload or {}
    applied = {}
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
        summary=f"Cross-verified contact applied; fields={','.join(applied) or 'none'}",
        metadata_json={
            "applied_fields": applied,
            "lookup_basis": packet["lookup_basis"],
            "owner_record_verified": bool(packet["owner_record"]["verified"]),
            "resolution_status": summary["status"],
            "outreach_allowed": False,
            "requires_downstream_compliance_review": True,
        },
    ))
    db.commit()
    return {
        "lead_id": lead.id,
        "status": summary["status"],
        "lookup_basis": packet["lookup_basis"],
        "applied": applied,
        "outreach_allowed": False,
        "next_gate": "DNC/TCPA/state/compliance review before any automated SMS or call.",
    }

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity
from .batchdata_adapter import BatchDataConfigurationError, BatchDataLookupError, lookup_batchdata_contacts
from .crm import _assert_linked
from .database import get_db
from .intelligence_ingest import ingest_provider_facts
from .models import Lead

router = APIRouter(prefix="/enrichment", tags=["contact enrichment"])


def _contact_review(lead: Lead, evidence: dict) -> dict:
    phones = evidence.get("phones") or []
    emails = evidence.get("emails") or []
    current_phone = str(lead.phone or "").strip()
    current_email = str(lead.email or "").strip().lower()
    safe_phones = evidence.get("safe_phone_candidates") or []
    blocked_phones = evidence.get("blocked_phone_candidates") or []
    proposed = {}
    if not current_phone and safe_phones:
        proposed["phone"] = safe_phones[0]["number"]
    if not current_email and emails:
        proposed["email"] = emails[0]["email"]
    conflicts = []
    if current_phone and phones and all(str(item.get("number") or "").strip() != current_phone for item in phones):
        conflicts.append({"field": "phone", "current": current_phone, "incoming": [item.get("number") for item in phones]})
    if current_email and emails and all(str(item.get("email") or "").strip().lower() != current_email for item in emails):
        conflicts.append({"field": "email", "current": current_email, "incoming": [item.get("email") for item in emails]})
    if evidence.get("owner_name") and lead.seller_name and evidence["owner_name"].strip().lower() != lead.seller_name.strip().lower():
        conflicts.append({"field": "owner_vs_seller", "current": lead.seller_name, "incoming": evidence["owner_name"], "requires": "right_party_and_county_record_verification"})
    compliance_blocks = []
    if blocked_phones:
        compliance_blocks.append("dnc_or_litigator_match")
    if not safe_phones:
        compliance_blocks.append("no_safe_phone_candidate")
    return {"proposed_updates": proposed, "conflicts": conflicts, "compliance_blocks": compliance_blocks, "requires_human_review": bool(conflicts or compliance_blocks), "outreach_allowed": bool(evidence.get("outreach_allowed")) and not compliance_blocks}


async def _lookup_for_lead(lead: Lead) -> dict:
    prop = lead.property
    if not prop:
        raise HTTPException(404, "Lead property not found")
    if str(prop.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    if not all(str(value or "").strip() for value in (prop.address, prop.city, prop.state, prop.zip_code)):
        raise HTTPException(422, "Complete property address is required")
    try:
        return await lookup_batchdata_contacts(address=prop.address, city=prop.city, state=prop.state, zip_code=prop.zip_code, owner_name=lead.seller_name)
    except BatchDataConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except BatchDataLookupError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/leads/{lead_id}/batchdata-preview")
async def preview_batchdata_enrichment(lead_id: int, principal: Principal = Depends(require_role("acquisitions")), db: Session = Depends(get_db)):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    evidence = await _lookup_for_lead(lead)
    return {"lead_id": lead.id, "provider": "batchdata", "evidence": evidence, "review": _contact_review(lead, evidence), "applied": False}


@router.post("/leads/{lead_id}/batchdata-apply")
async def apply_batchdata_enrichment(lead_id: int, payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    _assert_linked(db, principal, "lead", lead_id)
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    evidence = await _lookup_for_lead(lead)
    review = _contact_review(lead, evidence)
    payload = payload or {}
    approved_fields = {str(item) for item in payload.get("approved_fields", [])}
    force = bool(payload.get("force", False))
    applied = {}
    safe_phones = evidence.get("safe_phone_candidates") or []
    emails = evidence.get("emails") or []
    conflict_fields = {item["field"] for item in review["conflicts"]}
    if safe_phones:
        incoming_phone = safe_phones[0]["number"]
        if (not lead.phone or force or "phone" in approved_fields) and ("phone" not in conflict_fields or force or "phone" in approved_fields):
            lead.phone = incoming_phone
            applied["phone"] = incoming_phone
    if emails:
        incoming_email = emails[0]["email"]
        if (not lead.email or force or "email" in approved_fields) and ("email" not in conflict_fields or force or "email" in approved_fields):
            lead.email = incoming_email
            applied["email"] = incoming_email
    outreach_allowed = review["outreach_allowed"] and bool(payload.get("confirm_compliance_review", False))
    observed_text = evidence.get("observed_at")
    try:
        observed = datetime.fromisoformat(str(observed_text).replace("Z", "+00:00")).replace(tzinfo=None) if observed_text else datetime.utcnow()
    except ValueError:
        observed = datetime.utcnow()
    phone_values = [item.get("number") for item in evidence.get("phones") or [] if item.get("number")]
    email_values = [item.get("email") for item in emails if item.get("email")]
    seller_facts = {
        "seller_name": lead.seller_name,
        "reported_owner_name": evidence.get("owner_name"),
        "phone": phone_values[0] if phone_values else None,
        "phone_candidates": evidence.get("phones") or [],
        "email": email_values[0] if email_values else None,
        "email_candidates": emails,
        "blocked_phone_candidates": evidence.get("blocked_phone_candidates") or [],
        "outreach_allowed": outreach_allowed,
        "compliance_blocks": review.get("compliance_blocks") or [],
    }
    intelligence = ingest_provider_facts(
        db, principal.organization_id, "seller", lead.id, "batchdata", seller_facts,
        confidence=float(evidence.get("confidence") or 0), source_reference=str(evidence.get("raw_reference") or "") or None,
        verification_status="partially_verified", observed_at=observed,
        metadata={"verification_required": evidence.get("verification_required"), "property_id": lead.property.id if lead.property else None},
    )
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id,
        activity_type="contact_enriched", summary=f"BatchData evidence reviewed for {lead.seller_name}; {len(applied)} fields applied",
        metadata_json={"provider": "batchdata", "observed_at": evidence.get("observed_at") or datetime.utcnow().isoformat(), "confidence": evidence.get("confidence"), "owner_name": evidence.get("owner_name"), "phones": evidence.get("phones"), "emails": evidence.get("emails"), "blocked_phone_candidates": evidence.get("blocked_phone_candidates"), "source_reference": evidence.get("raw_reference"), "verification_required": evidence.get("verification_required"), "applied_fields": applied, "conflicts": review.get("conflicts"), "compliance_blocks": review.get("compliance_blocks"), "outreach_allowed": outreach_allowed, "intelligence": intelligence},
    ))
    db.commit()
    return {"lead_id": lead.id, "provider": "batchdata", "applied": applied, "conflicts": review["conflicts"], "compliance_blocks": review["compliance_blocks"], "outreach_allowed": outreach_allowed, "intelligence": intelligence, "note": "Applying contact data never initiates outreach; campaigns remain approval-gated."}

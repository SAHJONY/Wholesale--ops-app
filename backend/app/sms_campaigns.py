from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .compliance import normalize_phone
from .compliance_models import ContactSuppression
from .database import get_db
from .models import Lead, OpsTask
from .sms_campaign_models import SmsCampaign, SmsCampaignRecipient, SmsMessageTemplate, SmsSmartList
from .sms_engine import MAX_MESSAGES_PER_WINDOW, recent_message_count, validate_body

router = APIRouter(prefix="/sms-campaigns", tags=["SAHJONY SMS acquisition campaigns"])

MERGE_FIELD = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
SUPPORTED_FIELDS = frozenset({
    "first_name", "seller_name", "property_address", "city", "state", "zip_code",
    "company", "source", "asking_price", "arv", "mao",
})


def _workspace_leads(db: Session, organization_id: int) -> list[Lead]:
    ids = db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
    )).all()
    if not ids:
        return []
    return list(db.scalars(select(Lead).where(Lead.id.in_(ids)).order_by(Lead.created_at.desc())).all())


def _filter_values(filters: dict, key: str) -> set[str]:
    raw = filters.get(key) or []
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def lead_matches(lead: Lead, filters: dict) -> bool:
    property_record = lead.property
    states = _filter_values(filters, "states")
    zip_codes = _filter_values(filters, "zip_codes")
    statuses = _filter_values(filters, "statuses")
    sources = _filter_values(filters, "sources")
    if states and str(getattr(property_record, "state", "") or "").lower() not in states:
        return False
    if zip_codes and str(getattr(property_record, "zip_code", "") or "").lower() not in zip_codes:
        return False
    if statuses and str(lead.status or "").lower() not in statuses:
        return False
    if sources and str(lead.source or "").lower() not in sources:
        return False

    min_motivation = filters.get("min_motivation")
    if min_motivation not in (None, "") and float(lead.motivation_score or 0) < float(min_motivation):
        return False
    min_distress = filters.get("min_distress")
    if min_distress not in (None, "") and float(lead.distress_score or 0) < float(min_distress):
        return False
    max_timeline = filters.get("max_timeline_days")
    if max_timeline not in (None, ""):
        if lead.timeline_days is None or int(lead.timeline_days) > int(max_timeline):
            return False
    if filters.get("has_phone", True) and not normalize_phone(str(lead.phone or "")):
        return False

    search = str(filters.get("search") or "").strip().lower()
    if search:
        haystack = " ".join(str(item or "") for item in (
            lead.seller_name, lead.phone, lead.source, lead.status,
            getattr(property_record, "address", ""), getattr(property_record, "city", ""),
            getattr(property_record, "state", ""), getattr(property_record, "zip_code", ""),
        )).lower()
        if search not in haystack:
            return False
    return True


def _money(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return ""


def render_message(body: str, lead: Lead) -> str:
    property_record = lead.property
    seller_name = str(lead.seller_name or "").strip()
    first_name = seller_name.split()[0] if seller_name else "there"
    values = {
        "first_name": first_name,
        "seller_name": seller_name,
        "property_address": str(getattr(property_record, "address", "") or ""),
        "city": str(getattr(property_record, "city", "") or ""),
        "state": str(getattr(property_record, "state", "") or ""),
        "zip_code": str(getattr(property_record, "zip_code", "") or ""),
        "company": "SAHJONY",
        "source": str(lead.source or ""),
        "asking_price": _money(getattr(property_record, "asking_price", None)),
        "arv": _money(getattr(property_record, "arv", None)),
        "mao": _money(getattr(property_record, "mao", None)),
    }

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return MERGE_FIELD.sub(replace, body).strip()


def _validate_merge_fields(body: str) -> list[str]:
    return sorted({match.group(1) for match in MERGE_FIELD.finditer(body) if match.group(1) not in SUPPORTED_FIELDS})


def _smart_list(db: Session, principal: Principal, list_id: int) -> SmsSmartList:
    item = db.get(SmsSmartList, list_id)
    if not item or item.organization_id != principal.organization_id:
        raise HTTPException(404, "Smart list not found")
    return item


def _template(db: Session, principal: Principal, template_id: int) -> SmsMessageTemplate:
    item = db.get(SmsMessageTemplate, template_id)
    if not item or item.organization_id != principal.organization_id:
        raise HTTPException(404, "Message template not found")
    return item


def _campaign(db: Session, principal: Principal, campaign_id: int) -> SmsCampaign:
    item = db.get(SmsCampaign, campaign_id)
    if not item or item.organization_id != principal.organization_id:
        raise HTTPException(404, "Campaign not found")
    return item


@router.get("/summary")
def summary(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    lists = db.scalars(select(SmsSmartList).where(SmsSmartList.organization_id == principal.organization_id)).all()
    templates = db.scalars(select(SmsMessageTemplate).where(
        SmsMessageTemplate.organization_id == principal.organization_id,
        SmsMessageTemplate.is_active.is_(True),
    )).all()
    campaigns = db.scalars(select(SmsCampaign).where(
        SmsCampaign.organization_id == principal.organization_id,
    ).order_by(SmsCampaign.created_at.desc())).all()
    return {
        "smart_lists": len(lists),
        "templates": len(templates),
        "campaigns": len(campaigns),
        "prepared_recipients": sum(item.prepared_count for item in campaigns),
        "needs_compliance": sum(item.ready_count for item in campaigns),
    }


@router.get("/smart-lists")
def list_smart_lists(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    items = db.scalars(select(SmsSmartList).where(
        SmsSmartList.organization_id == principal.organization_id,
    ).order_by(SmsSmartList.created_at.desc())).all()
    leads = _workspace_leads(db, principal.organization_id)
    return [{
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "filters": item.filters,
        "audience_count": sum(1 for lead in leads if lead_matches(lead, item.filters or {})),
        "created_at": item.created_at,
    } for item in items]


@router.post("/smart-lists")
def create_smart_list(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Smart list name is required")
    item = SmsSmartList(
        organization_id=principal.organization_id,
        name=name,
        description=str(payload.get("description") or "").strip() or None,
        filters=payload.get("filters") if isinstance(payload.get("filters"), dict) else {},
        created_by_user_id=principal.user_id,
    )
    db.add(item)
    db.flush()
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id,
        activity_type="sms_smart_list_created", summary=f"SMS smart list created: {item.name}",
        metadata_json={"smart_list_id": item.id, "filters": item.filters},
    ))
    db.commit()
    return {"id": item.id, "name": item.name, "filters": item.filters}


@router.post("/audience-preview")
def audience_preview(payload: dict, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    leads = [lead for lead in _workspace_leads(db, principal.organization_id) if lead_matches(lead, filters)]
    return {
        "count": len(leads),
        "sample": [{
            "id": lead.id, "seller_name": lead.seller_name, "phone": lead.phone,
            "status": lead.status, "source": lead.source,
            "city": getattr(lead.property, "city", None), "state": getattr(lead.property, "state", None),
            "zip_code": getattr(lead.property, "zip_code", None),
        } for lead in leads[:25]],
    }


@router.get("/templates")
def list_templates(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    items = db.scalars(select(SmsMessageTemplate).where(
        SmsMessageTemplate.organization_id == principal.organization_id,
    ).order_by(SmsMessageTemplate.created_at.desc())).all()
    return [{
        "id": item.id, "name": item.name, "body": item.body,
        "pathway_id": item.pathway_id, "persona_id": item.persona_id,
        "is_active": item.is_active, "created_at": item.created_at,
    } for item in items]


@router.post("/templates")
def create_template(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    name = str(payload.get("name") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not name or not body:
        raise HTTPException(422, "Template name and body are required")
    unknown = _validate_merge_fields(body)
    if unknown:
        raise HTTPException(422, f"Unsupported merge fields: {', '.join(unknown)}")
    item = SmsMessageTemplate(
        organization_id=principal.organization_id,
        name=name,
        body=body,
        pathway_id=str(payload.get("pathway_id") or "").strip() or None,
        persona_id=str(payload.get("persona_id") or "").strip() or None,
        created_by_user_id=principal.user_id,
    )
    db.add(item)
    db.flush()
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id,
        activity_type="sms_template_created", summary=f"SMS template created: {item.name}",
        metadata_json={"template_id": item.id},
    ))
    db.commit()
    return {"id": item.id, "name": item.name, "body": item.body}


@router.get("")
def list_campaigns(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    items = db.scalars(select(SmsCampaign).where(
        SmsCampaign.organization_id == principal.organization_id,
    ).order_by(SmsCampaign.created_at.desc())).all()
    return [{
        "id": item.id, "name": item.name, "status": item.status,
        "smart_list_id": item.smart_list_id, "template_id": item.template_id,
        "audience_count": item.audience_count, "prepared_count": item.prepared_count,
        "suppressed_count": item.suppressed_count, "ready_count": item.ready_count,
        "created_at": item.created_at, "updated_at": item.updated_at,
    } for item in items]


@router.post("")
def create_campaign(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Campaign name is required")
    smart_list_id = int(payload.get("smart_list_id") or 0) or None
    template_id = int(payload.get("template_id") or 0) or None
    if not smart_list_id or not template_id:
        raise HTTPException(422, "A smart list and message template are required")
    smart_list = _smart_list(db, principal, smart_list_id)
    _template(db, principal, template_id)
    audience = [lead for lead in _workspace_leads(db, principal.organization_id) if lead_matches(lead, smart_list.filters or {})]
    item = SmsCampaign(
        organization_id=principal.organization_id,
        name=name,
        status="draft",
        smart_list_id=smart_list_id,
        template_id=template_id,
        filters_snapshot=smart_list.filters or {},
        audience_count=len(audience),
        created_by_user_id=principal.user_id,
        metadata_json={"brand": "SAHJONY AI Acquisition", "transport": "bland"},
    )
    db.add(item)
    db.flush()
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id,
        activity_type="sms_campaign_created", summary=f"SMS campaign created: {item.name}",
        metadata_json={"campaign_id": item.id, "audience_count": item.audience_count},
    ))
    db.commit()
    return {"id": item.id, "name": item.name, "status": item.status, "audience_count": item.audience_count}


@router.post("/{campaign_id}/prepare")
def prepare_campaign(campaign_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    campaign = _campaign(db, principal, campaign_id)
    if campaign.status in {"active", "completed"}:
        raise HTTPException(409, "Active or completed campaigns cannot be re-prepared")
    if not campaign.template_id:
        raise HTTPException(422, "Campaign has no template")
    template = _template(db, principal, campaign.template_id)
    filters = campaign.filters_snapshot or {}
    leads = [lead for lead in _workspace_leads(db, principal.organization_id) if lead_matches(lead, filters)]

    db.execute(delete(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
    ))

    prepared = suppressed = needs_compliance = blocked_content = 0
    now = datetime.now(timezone.utc)
    for lead in leads:
        contact = normalize_phone(str(lead.phone or ""))
        if not contact:
            continue
        body = render_message(template.body, lead)
        blockers = validate_body(body)
        suppression = db.scalar(select(ContactSuppression).where(
            ContactSuppression.organization_id == principal.organization_id,
            ContactSuppression.contact == contact,
            ContactSuppression.channel.in_(["sms", "phone", "all"]),
            ContactSuppression.active.is_(True),
        ))
        frequency_count = recent_message_count(db, principal.organization_id, contact, now)

        status = "needs_compliance"
        reason = None
        if suppression:
            status = "suppressed"
            reason = suppression.reason or "contact_suppressed"
            suppressed += 1
        elif blockers:
            status = "blocked_content"
            reason = ",".join(blockers)
            blocked_content += 1
        elif frequency_count >= MAX_MESSAGES_PER_WINDOW:
            status = "frequency_capped"
            reason = "rolling_frequency_limit"
        else:
            needs_compliance += 1

        db.add(SmsCampaignRecipient(
            organization_id=principal.organization_id,
            campaign_id=campaign.id,
            lead_id=lead.id,
            contact=contact,
            rendered_body=body,
            status=status,
            suppression_reason=reason,
            evidence={
                "template_id": template.id,
                "pathway_id": template.pathway_id,
                "persona_id": template.persona_id,
                "frequency_count": frequency_count,
                "prepared_at": now.isoformat(),
            },
        ))
        prepared += 1

    campaign.status = "prepared"
    campaign.audience_count = len(leads)
    campaign.prepared_count = prepared
    campaign.suppressed_count = suppressed
    campaign.ready_count = needs_compliance
    campaign.metadata_json = {
        **(campaign.metadata_json or {}),
        "blocked_content": blocked_content,
        "prepared_at": now.isoformat(),
        "execution_boundary": "recipient rows require individual compliance decision and owner approval before Bland dispatch",
    }
    db.add(OpsTask(
        task_type="sms_campaign_compliance_queue",
        status="queued",
        priority=80,
        payload={
            "organization_id": principal.organization_id,
            "campaign_id": campaign.id,
            "recipient_count": needs_compliance,
            "provider": "bland",
        },
        requires_approval=False,
    ))
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id,
        activity_type="sms_campaign_prepared", summary=f"SMS campaign prepared: {campaign.name}",
        metadata_json={
            "campaign_id": campaign.id, "prepared": prepared, "suppressed": suppressed,
            "needs_compliance": needs_compliance, "blocked_content": blocked_content,
        },
    ))
    db.commit()
    return {
        "campaign_id": campaign.id, "status": campaign.status,
        "audience_count": campaign.audience_count, "prepared_count": prepared,
        "suppressed_count": suppressed, "needs_compliance": needs_compliance,
        "blocked_content": blocked_content,
        "dispatch_allowed": False,
        "next_step": "Run recipient-level compliance evaluation, obtain owner approval, then dispatch through Bland.",
    }


@router.get("/{campaign_id}/recipients")
def campaign_recipients(campaign_id: int, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    campaign = _campaign(db, principal, campaign_id)
    rows = db.scalars(select(SmsCampaignRecipient).where(
        SmsCampaignRecipient.organization_id == principal.organization_id,
        SmsCampaignRecipient.campaign_id == campaign.id,
    ).order_by(SmsCampaignRecipient.id.asc()).limit(500)).all()
    lead_ids = {row.lead_id for row in rows}
    lead_map = {lead.id: lead for lead in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()} if lead_ids else {}
    return [{
        "id": row.id, "lead_id": row.lead_id,
        "seller_name": getattr(lead_map.get(row.lead_id), "seller_name", None),
        "contact": row.contact, "rendered_body": row.rendered_body,
        "status": row.status, "suppression_reason": row.suppression_reason,
        "outbound_request_id": row.outbound_request_id,
    } for row in rows]

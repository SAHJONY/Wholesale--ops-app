import os
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .deal_execution_models import ContractPacket, DealDocument
from .models import Approval, Deal, Lead, Property
from .operating_system import initialize_closing

router = APIRouter(prefix="/deal-execution", tags=["deal execution"])

PACKET_TYPES = {"purchase_agreement", "assignment_agreement"}


def _deal_context(db: Session, principal: Principal, deal_id: int):
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    lead = db.get(Lead, prop.lead_id) if prop else None
    if not prop or not lead:
        raise HTTPException(422, "Deal requires a linked property and seller lead")
    if str(prop.state or "").upper() == "TX":
        raise HTTPException(422, "Texas is excluded from SAHJONY acquisition workflows")
    return deal, prop, lead


def _template_for(packet_type: str, state: str) -> str | None:
    state_key = str(state or "").upper()
    specific = os.getenv(f"DOCUSIGN_TEMPLATE_{packet_type.upper()}_{state_key}")
    generic = os.getenv(f"DOCUSIGN_TEMPLATE_{packet_type.upper()}")
    return specific or generic


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    deal_ids = list(db.scalars(select(__import__('app.auth_models', fromlist=['WorkspaceEntity']).WorkspaceEntity.entity_id).where(
        __import__('app.auth_models', fromlist=['WorkspaceEntity']).WorkspaceEntity.organization_id == principal.organization_id,
        __import__('app.auth_models', fromlist=['WorkspaceEntity']).WorkspaceEntity.entity_type == "deal",
    )).all())
    deals = db.scalars(select(Deal).where(Deal.id.in_(deal_ids)).order_by(Deal.updated_at.desc())).all() if deal_ids else []
    packets = db.scalars(select(ContractPacket).where(
        ContractPacket.organization_id == principal.organization_id
    ).order_by(ContractPacket.created_at.desc())).all()
    documents = db.scalars(select(DealDocument).where(
        DealDocument.organization_id == principal.organization_id
    ).order_by(DealDocument.created_at.desc())).all()
    return {
        "deals": [{
            "id": d.id, "property_id": d.property_id, "stage": d.stage,
            "target_contract_price": d.target_contract_price,
            "target_buyer_price": d.target_buyer_price,
            "projected_assignment_fee": d.projected_assignment_fee,
            "next_action": d.next_action,
        } for d in deals],
        "packets": [{
            "id": p.id, "deal_id": p.deal_id, "packet_type": p.packet_type,
            "status": p.status, "signer_name": p.signer_name, "signer_email": p.signer_email,
            "template_id": p.template_id, "provider_status": p.provider_status,
            "docusign_envelope_id": p.docusign_envelope_id, "error": p.error,
            "created_at": p.created_at, "sent_at": p.sent_at,
        } for p in packets],
        "documents": [{
            "id": d.id, "deal_id": d.deal_id, "packet_id": d.packet_id,
            "document_type": d.document_type, "status": d.status,
            "storage_key": d.storage_key, "source": d.source,
        } for d in documents],
        "readiness": {
            "docusign_account": bool(os.getenv("DOCUSIGN_ACCOUNT_ID")),
            "docusign_token": bool(os.getenv("DOCUSIGN_ACCESS_TOKEN")),
            "document_storage": bool(os.getenv("S3_BUCKET") and os.getenv("S3_ACCESS_KEY_ID") and os.getenv("S3_SECRET_ACCESS_KEY")),
        },
    }


@router.post("/deals/{deal_id}/packets")
def prepare_packet(
    deal_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    deal, prop, lead = _deal_context(db, principal, deal_id)
    packet_type = str(payload.get("packet_type") or "purchase_agreement").strip().lower()
    if packet_type not in PACKET_TYPES:
        raise HTTPException(422, "Unsupported packet type")
    signer_name = str(payload.get("signer_name") or lead.seller_name or "").strip()
    signer_email = str(payload.get("signer_email") or lead.email or "").strip().lower()
    if not signer_name or not signer_email:
        raise HTTPException(422, "Signer name and email are required")
    template_id = str(payload.get("template_id") or _template_for(packet_type, prop.state) or "").strip()
    if not template_id:
        raise HTTPException(503, "An attorney-approved DocuSign template is not configured for this packet and state")

    contract_price = float(payload.get("contract_price") or deal.target_contract_price or prop.mao or 0)
    if contract_price <= 0:
        raise HTTPException(422, "A verified contract price is required")
    assignment_fee = float(payload.get("assignment_fee") or deal.projected_assignment_fee or 0)
    closing_days = max(1, int(payload.get("closing_days") or 30))
    effective_date = str(payload.get("effective_date") or datetime.utcnow().date().isoformat())
    closing_date = str(payload.get("closing_date") or (datetime.utcnow() + timedelta(days=closing_days)).date().isoformat())

    terms = {
        "buyer_name": str(payload.get("buyer_name") or "Juan Gonzalez"),
        "contract_price": contract_price,
        "assignment_fee": assignment_fee,
        "earnest_money": float(payload.get("earnest_money") or 100),
        "closing_days": closing_days,
        "assignment_allowed": bool(payload.get("assignment_allowed", True)),
        "buyer_pays_closing": bool(payload.get("buyer_pays_closing", True)),
        "effective_date": effective_date,
        "closing_date": closing_date,
    }
    merge_data = {
        "seller_name": signer_name,
        "seller_email": signer_email,
        "property_address": prop.address,
        "property_city": prop.city,
        "property_state": prop.state,
        "property_zip": prop.zip_code,
        **terms,
    }
    packet = ContractPacket(
        organization_id=principal.organization_id,
        deal_id=deal.id,
        packet_type=packet_type,
        status="pending_approval",
        template_id=template_id,
        template_version=str(payload.get("template_version") or "approved-current"),
        signer_name=signer_name,
        signer_email=signer_email,
        terms=terms,
        merge_data=merge_data,
        created_by_user_id=principal.user_id,
    )
    db.add(packet)
    db.flush()
    _workspace_link(db, principal.organization_id, "contract_packet", packet.id)
    approval = Approval(
        action_type=f"send_{packet_type}", status="pending", entity_type="contract_packet",
        entity_id=packet.id, summary=f"Approve {packet_type.replace('_', ' ')} for deal #{deal.id}",
        payload={"packet_id": packet.id, "deal_id": deal.id, "terms": terms},
    )
    db.add(approval)
    db.flush()
    _workspace_link(db, principal.organization_id, "approval", approval.id)
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id,
        deal_id=deal.id, activity_type="contract_packet_prepared",
        summary=f"{packet_type.replace('_', ' ').title()} prepared; owner approval required",
        metadata_json={"packet_id": packet.id, "approval_id": approval.id, "template_id": template_id, "terms": terms},
    ))
    db.commit()
    return {"packet_id": packet.id, "approval_id": approval.id, "status": packet.status, "terms": terms}


def _approved(db: Session, packet_id: int):
    return db.scalar(select(Approval).where(
        Approval.entity_type == "contract_packet", Approval.entity_id == packet_id,
        Approval.status == "approved",
    ).order_by(Approval.decided_at.desc()))


@router.post("/packets/{packet_id}/send")
async def send_packet(
    packet_id: int,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    packet = db.get(ContractPacket, packet_id)
    if not packet or packet.organization_id != principal.organization_id:
        raise HTTPException(404, "Contract packet not found")
    if packet.status in {"sent", "completed"}:
        return {"packet_id": packet.id, "status": packet.status, "envelope_id": packet.docusign_envelope_id}
    approval = _approved(db, packet.id)
    if not approval:
        raise HTTPException(409, "Owner approval is required before sending")
    account_id = os.getenv("DOCUSIGN_ACCOUNT_ID")
    access_token = os.getenv("DOCUSIGN_ACCESS_TOKEN")
    base_path = (os.getenv("DOCUSIGN_BASE_PATH") or "https://demo.docusign.net/restapi").rstrip("/")
    if not account_id or not access_token:
        raise HTTPException(503, "DocuSign account and access token are not configured")

    tabs = [{"tabLabel": key, "value": str(value)} for key, value in packet.merge_data.items() if value not in (None, "")]
    body = {
        "templateId": packet.template_id,
        "templateRoles": [{
            "email": packet.signer_email,
            "name": packet.signer_name,
            "roleName": os.getenv("DOCUSIGN_SELLER_ROLE_NAME") or "Seller",
            "tabs": {"textTabs": tabs},
        }],
        "status": "sent",
        "emailSubject": f"SAHJONY {packet.packet_type.replace('_', ' ').title()} — Deal #{packet.deal_id}",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_path}/v2.1/accounts/{account_id}/envelopes",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json=body,
        )
    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text[:1000]}
    if response.status_code >= 400:
        packet.status = "failed"; packet.error = str(data.get("message") or response.status_code); db.commit()
        raise HTTPException(502, f"DocuSign rejected the envelope: {packet.error}")

    packet.status = "sent"
    packet.provider_status = data.get("status") or "sent"
    packet.docusign_envelope_id = data.get("envelopeId")
    packet.approved_by_user_id = principal.user_id
    packet.sent_at = datetime.utcnow()
    packet.error = None
    db.add(DealDocument(
        organization_id=principal.organization_id, deal_id=packet.deal_id, packet_id=packet.id,
        document_type=packet.packet_type, status="signature_pending", source="docusign",
        metadata_json={"envelope_id": packet.docusign_envelope_id},
    ))
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, deal_id=packet.deal_id,
        activity_type="contract_packet_sent", summary=f"{packet.packet_type.replace('_', ' ').title()} sent through DocuSign",
        metadata_json={"packet_id": packet.id, "envelope_id": packet.docusign_envelope_id},
    ))
    db.commit()
    return {"packet_id": packet.id, "status": packet.status, "envelope_id": packet.docusign_envelope_id}


@router.post("/deals/{deal_id}/initialize-closing")
def initialize_deal_closing(
    deal_id: int,
    principal: Principal = Depends(require_role("transaction_coordinator")),
    db: Session = Depends(get_db),
):
    deal, prop, lead = _deal_context(db, principal, deal_id)
    items = initialize_closing(db, deal.id)
    deal.stage = "closing"
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id,
        deal_id=deal.id, activity_type="closing_initialized",
        summary=f"Closing checklist initialized for {prop.address}",
        metadata_json={"items": [item.item_type for item in items]},
    ))
    db.commit()
    return {"deal_id": deal.id, "stage": deal.stage, "items": [{"id": i.id, "type": i.item_type, "status": i.status} for i in items]}

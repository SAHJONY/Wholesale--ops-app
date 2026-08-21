import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .crm import _assert_linked, _workspace_link
from .database import get_db
from .deal_execution_models import ContractPacket, DealDocument
from .models import Approval, Deal, Lead, Property
from .operating_system import initialize_closing

router = APIRouter(prefix="/deal-execution", tags=["deal execution"])

PACKET_TYPES = {"purchase_agreement", "assignment_agreement"}
SIGNATURE_PROVIDERS = {"docuseal", "docusign", "manual"}


def _deal_context(db: Session, principal: Principal, deal_id: int):
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")
    prop = db.get(Property, deal.property_id)
    lead = db.get(Lead, prop.lead_id) if prop else None
    if not prop or not lead:
        raise HTTPException(422, "Deal requires a linked property and seller lead")
    # State-specific contract and assignment constraints are enforced by the
    # compliance/template/title layers. Deal Execution must not hard-block a
    # state through a legacy market policy; Texas deals still require approved
    # state-appropriate templates, human approval, and closing/title evidence.
    return deal, prop, lead


def _provider(payload: dict | None = None) -> str:
    requested = str((payload or {}).get("signature_provider") or os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").strip().lower()
    if requested not in SIGNATURE_PROVIDERS:
        raise HTTPException(422, "Supported signature providers are docuseal, docusign, and manual")
    return requested


def _template_for(provider: str, packet_type: str, state: str) -> str | None:
    state_key = str(state or "").upper()
    prefix = "CONTRACT" if provider == "manual" else "DOCUSEAL" if provider == "docuseal" else "DOCUSIGN"
    specific = os.getenv(f"{prefix}_TEMPLATE_{packet_type.upper()}_{state_key}")
    generic = os.getenv(f"{prefix}_TEMPLATE_{packet_type.upper()}")
    return specific or generic


def _packet_provider(packet: ContractPacket) -> str:
    provider = str((packet.terms or {}).get("signature_provider") or "").strip().lower()
    if provider in SIGNATURE_PROVIDERS:
        return provider
    return "docusign" if packet.docusign_envelope_id else str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower()


def _blob_storage_ready() -> bool:
    return bool((os.getenv("BLOB_READ_WRITE_TOKEN") or "").strip())


def _manual_contracts_ready() -> bool:
    return os.getenv("CONTRACT_EXECUTION_MODE") == "manual_governed" and _blob_storage_ready()


def _provider_readiness() -> dict:
    selected = str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower()
    docuseal_ready = bool(os.getenv("DOCUSEAL_API_KEY") and os.getenv("DOCUSEAL_URL"))
    docusign_ready = bool(os.getenv("DOCUSIGN_ACCOUNT_ID") and os.getenv("DOCUSIGN_ACCESS_TOKEN"))
    manual_ready = _manual_contracts_ready()
    return {
        "selected_provider": selected,
        "provider_configured": manual_ready if selected == "manual" else docuseal_ready if selected == "docuseal" else docusign_ready,
        "docuseal_configured": docuseal_ready,
        "docusign_configured": docusign_ready,
        "manual_governed_configured": manual_ready,
        "document_storage": _blob_storage_ready() or bool(os.getenv("S3_BUCKET") and os.getenv("S3_ACCESS_KEY_ID") and os.getenv("S3_SECRET_ACCESS_KEY")),
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    deal_ids = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
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
            "template_id": p.template_id, "provider": _packet_provider(p),
            "provider_status": p.provider_status,
            "provider_reference": p.docusign_envelope_id,
            "docusign_envelope_id": p.docusign_envelope_id,
            "error": p.error, "created_at": p.created_at, "sent_at": p.sent_at,
        } for p in packets],
        "documents": [{
            "id": d.id, "deal_id": d.deal_id, "packet_id": d.packet_id,
            "document_type": d.document_type, "status": d.status,
            "storage_key": d.storage_key, "source": d.source,
        } for d in documents],
        "readiness": _provider_readiness(),
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
    provider = _provider(payload)
    signer_name = str(payload.get("signer_name") or lead.seller_name or "").strip()
    signer_email = str(payload.get("signer_email") or lead.email or "").strip().lower()
    if not signer_name or not signer_email:
        raise HTTPException(422, "Signer name and email are required")
    template_id = str(payload.get("template_id") or _template_for(provider, packet_type, prop.state) or "").strip()
    if not template_id:
        raise HTTPException(503, f"An attorney-approved {provider.title()} template is not configured for this packet and state")

    contract_price = float(payload.get("contract_price") or deal.target_contract_price or prop.mao or 0)
    if contract_price <= 0:
        raise HTTPException(422, "A verified contract price is required")
    assignment_fee = float(payload.get("assignment_fee") or deal.projected_assignment_fee or 0)
    closing_days = max(1, int(payload.get("closing_days") or 30))
    effective_date = str(payload.get("effective_date") or datetime.now(timezone.utc).date().isoformat())
    closing_date = str(payload.get("closing_date") or (datetime.now(timezone.utc) + timedelta(days=closing_days)).date().isoformat())

    terms = {
        "signature_provider": provider,
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
        entity_id=packet.id, summary=f"Approve {packet_type.replace('_', ' ')} for deal #{deal.id} via {provider.title()}",
        payload={"packet_id": packet.id, "deal_id": deal.id, "provider": provider, "terms": terms},
    )
    db.add(approval)
    db.flush()
    _workspace_link(db, principal.organization_id, "approval", approval.id)
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, lead_id=lead.id,
        deal_id=deal.id, activity_type="contract_packet_prepared",
        summary=f"{packet_type.replace('_', ' ').title()} prepared for {provider.title()}; owner approval required",
        metadata_json={"packet_id": packet.id, "approval_id": approval.id, "provider": provider, "template_id": template_id, "terms": terms},
    ))
    db.commit()
    return {"packet_id": packet.id, "approval_id": approval.id, "status": packet.status, "provider": provider, "terms": terms}


def _approved(db: Session, packet_id: int):
    return db.scalar(select(Approval).where(
        Approval.entity_type == "contract_packet", Approval.entity_id == packet_id,
        Approval.status == "approved",
    ).order_by(Approval.decided_at.desc()))


async def _send_docuseal(packet: ContractPacket) -> dict:
    api_key = os.getenv("DOCUSEAL_API_KEY")
    base_url = str(os.getenv("DOCUSEAL_URL") or "").rstrip("/")
    if not api_key or not base_url:
        raise HTTPException(503, "DocuSeal URL and API key are not configured")
    try:
        template_id = int(str(packet.template_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "DocuSeal template ID must be numeric") from exc

    role = os.getenv("DOCUSEAL_SELLER_ROLE_NAME") or "Seller"
    body = {
        "template_id": template_id,
        "send_email": True,
        "order": "preserved",
        "submitters": [{
            "role": role,
            "name": packet.signer_name,
            "email": packet.signer_email,
            "values": {key: value for key, value in packet.merge_data.items() if value not in (None, "")},
            "external_id": f"sahjony-packet-{packet.id}",
            "metadata": {"packet_id": packet.id, "deal_id": packet.deal_id, "organization_id": packet.organization_id},
        }],
        "message": {
            "subject": f"SAHJONY {packet.packet_type.replace('_', ' ').title()} — Deal #{packet.deal_id}",
            "body": "Please review and sign the attached agreement. Use the secure link below: {{submitter.link}}",
        },
    }
    completed_redirect = os.getenv("DOCUSEAL_COMPLETED_REDIRECT_URL")
    reply_to = os.getenv("DOCUSEAL_REPLY_TO")
    bcc_completed = os.getenv("DOCUSEAL_BCC_COMPLETED")
    if completed_redirect:
        body["completed_redirect_url"] = completed_redirect
    if reply_to:
        body["reply_to"] = reply_to
    if bcc_completed:
        body["bcc_completed"] = bcc_completed

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/api/submissions",
            headers={"x-auth-token": api_key, "Content-Type": "application/json"},
            json=body,
        )
    try:
        data = response.json()
    except ValueError:
        data = {"error": response.text[:1000]}
    if response.status_code >= 400:
        raise HTTPException(502, f"DocuSeal rejected the submission: {data.get('error') or response.status_code}")

    rows = data if isinstance(data, list) else [data]
    first = rows[0] if rows else {}
    submission_id = first.get("submission_id") or first.get("id") or first.get("submission", {}).get("id")
    status = first.get("status") or "pending"
    return {
        "provider": "docuseal",
        "provider_reference": str(submission_id or first.get("slug") or ""),
        "provider_status": status,
        "provider_response": data,
    }


async def _send_docusign(packet: ContractPacket) -> dict:
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
        raise HTTPException(502, f"DocuSign rejected the envelope: {data.get('message') or response.status_code}")
    return {
        "provider": "docusign",
        "provider_reference": str(data.get("envelopeId") or ""),
        "provider_status": data.get("status") or "sent",
        "provider_response": data,
    }


@router.post("/packets/{packet_id}/send")
async def send_packet(
    packet_id: int,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    packet = db.get(ContractPacket, packet_id)
    if not packet or packet.organization_id != principal.organization_id:
        raise HTTPException(404, "Contract packet not found")
    provider = _packet_provider(packet)
    if packet.status in {"sent", "completed"}:
        return {"packet_id": packet.id, "status": packet.status, "provider": provider, "provider_reference": packet.docusign_envelope_id}
    if not _approved(db, packet.id):
        raise HTTPException(409, "Owner approval is required before sending")

    try:
        if provider == "manual":
            if not _manual_contracts_ready():
                raise HTTPException(503, "Governed manual contract execution and private document storage are not configured")
            result = {
                "provider": "manual",
                "provider_reference": f"manual-{packet.id}",
                "provider_status": "manual_signature_pending",
                "provider_response": {},
            }
        else:
            result = await (_send_docuseal(packet) if provider == "docuseal" else _send_docusign(packet))
    except HTTPException as exc:
        packet.status = "failed"
        packet.error = str(exc.detail)
        db.commit()
        raise

    packet.status = "sent"
    packet.provider_status = result["provider_status"]
    # Legacy database column retained as the generic provider-reference field.
    packet.docusign_envelope_id = result["provider_reference"]
    packet.approved_by_user_id = principal.user_id
    packet.sent_at = datetime.now(timezone.utc)
    packet.error = None
    db.add(DealDocument(
        organization_id=principal.organization_id, deal_id=packet.deal_id, packet_id=packet.id,
        document_type=packet.packet_type, status="signature_pending", source=provider,
        metadata_json={"provider": provider, "provider_reference": result["provider_reference"]},
    ))
    db.add(CrmActivity(
        organization_id=principal.organization_id, user_id=principal.user_id, deal_id=packet.deal_id,
        activity_type="contract_packet_sent",
        summary=f"{packet.packet_type.replace('_', ' ').title()} sent through {provider.title()}",
        metadata_json={"packet_id": packet.id, "provider": provider, "provider_reference": result["provider_reference"]},
    ))
    db.commit()
    return {
        "packet_id": packet.id,
        "status": packet.status,
        "provider": provider,
        "provider_reference": result["provider_reference"],
        "envelope_id": result["provider_reference"],
    }


@router.post("/packets/{packet_id}/manual-completion")
def complete_manual_packet(
    packet_id: int,
    payload: dict,
    principal: Principal = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    packet = db.get(ContractPacket, packet_id)
    if not packet or packet.organization_id != principal.organization_id:
        raise HTTPException(404, "Contract packet not found")
    if _packet_provider(packet) != "manual":
        raise HTTPException(409, "Only governed manual packets can be completed through this route")
    if packet.status != "sent" or packet.provider_status != "manual_signature_pending":
        raise HTTPException(409, "Manual packet must be approved and awaiting signature")

    storage_key = str(payload.get("storage_key") or "").strip()
    if not storage_key.startswith("https://") or ".blob.vercel-storage.com/" not in storage_key:
        raise HTTPException(422, "A private Vercel Blob document URL is required")

    document = db.scalar(select(DealDocument).where(DealDocument.packet_id == packet.id))
    if not document:
        document = DealDocument(
            organization_id=principal.organization_id,
            deal_id=packet.deal_id,
            packet_id=packet.id,
            document_type=packet.packet_type,
            source="manual",
        )
    document.status = "signed"
    document.storage_key = storage_key
    document.metadata_json = {
        **(document.metadata_json or {}),
        "verified_by_user_id": principal.user_id,
        "verification_method": "owner_attestation",
    }
    packet.status = "completed"
    packet.provider_status = "completed"
    packet.completed_at = datetime.now(timezone.utc)
    db.add_all([packet, document, CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deal_id=packet.deal_id,
        activity_type="manual_contract_completed",
        summary=f"Signed {packet.packet_type.replace('_', ' ')} registered in private document storage",
        metadata_json={"packet_id": packet.id, "storage_provider": "vercel_blob"},
    )])
    db.commit()
    return {"packet_id": packet.id, "status": packet.status, "document_id": document.id}


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

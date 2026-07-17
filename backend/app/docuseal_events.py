import os
import secrets
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity
from .database import get_db
from .deal_execution_models import ContractPacket, DealDocument
from .event_bus import emit_event
from .models import Deal
from .operating_system import initialize_closing

router = APIRouter(tags=["DocuSeal synchronization"])


def _configured_secret() -> str:
    return str(os.getenv("DOCUSEAL_WEBHOOK_SECRET") or "").strip()


def _authorized(secret: str | None, authorization: str | None) -> bool:
    expected = _configured_secret()
    if not expected:
        return False
    candidates = [str(secret or "").strip()]
    auth = str(authorization or "").strip()
    if auth.lower().startswith("bearer "):
        candidates.append(auth[7:].strip())
    return any(value and secrets.compare_digest(value, expected) for value in candidates)


def _submission(payload: dict) -> dict:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    submission = data.get("submission") if isinstance(data.get("submission"), dict) else data
    return submission if isinstance(submission, dict) else {}


def _packet_id(payload: dict, submission: dict) -> int | None:
    candidates = [
        submission.get("external_id"),
        (submission.get("metadata") or {}).get("packet_id") if isinstance(submission.get("metadata"), dict) else None,
        payload.get("packet_id"),
    ]
    submitters = submission.get("submitters") if isinstance(submission.get("submitters"), list) else []
    for item in submitters:
        if isinstance(item, dict):
            candidates.extend([item.get("external_id"), (item.get("metadata") or {}).get("packet_id") if isinstance(item.get("metadata"), dict) else None])
    for value in candidates:
        text = str(value or "")
        if text.startswith("sahjony-packet-"):
            text = text.rsplit("-", 1)[-1]
        if text.isdigit():
            return int(text)
    return None


def _status(payload: dict, submission: dict) -> str:
    event = str(payload.get("event_type") or payload.get("event") or payload.get("type") or "").lower()
    status = str(submission.get("status") or payload.get("status") or "").lower()
    combined = f"{event} {status}"
    if "complete" in combined:
        return "completed"
    if "declin" in combined:
        return "declined"
    if "expir" in combined:
        return "expired"
    if "sent" in combined or "pending" in combined or "created" in combined:
        return "sent"
    return status or "sent"


def _apply_status(db: Session, packet: ContractPacket, provider_status: str, payload: dict) -> None:
    packet.provider_status = provider_status
    packet.error = None
    if provider_status == "completed":
        packet.status = "completed"
        packet.completed_at = datetime.utcnow()
    elif provider_status in {"declined", "expired"}:
        packet.status = provider_status
    else:
        packet.status = "sent"

    document = db.scalar(select(DealDocument).where(DealDocument.packet_id == packet.id).order_by(DealDocument.id.desc()))
    if not document:
        document = DealDocument(
            organization_id=packet.organization_id,
            deal_id=packet.deal_id,
            packet_id=packet.id,
            document_type=packet.packet_type,
            source="docuseal",
        )
        db.add(document)
    document.status = "signed" if provider_status == "completed" else "signature_pending" if provider_status == "sent" else provider_status
    metadata = dict(document.metadata_json or {})
    metadata.update({"submission_id": packet.docusign_envelope_id, "last_event": payload})
    document.metadata_json = metadata

    if provider_status == "completed":
        deal = db.get(Deal, packet.deal_id)
        if deal and deal.stage not in {"closing", "closed", "dead"}:
            initialize_closing(db, deal.id)
            deal.stage = "closing"
            deal.next_action = "Coordinate title, earnest money, and closing milestones"
        emit_event(
            db,
            packet.organization_id,
            "ContractSigned",
            "deal",
            packet.deal_id,
            payload={"packet_id": packet.id, "packet_type": packet.packet_type, "submission_id": packet.docusign_envelope_id},
            source="docuseal",
            event_key=f"docuseal:contract-signed:{packet.id}",
        )

    db.add(CrmActivity(
        organization_id=packet.organization_id,
        deal_id=packet.deal_id,
        activity_type=f"docuseal_{provider_status}",
        summary=f"{packet.packet_type.replace('_', ' ').title()} is {provider_status} in DocuSeal",
        metadata_json={"packet_id": packet.id, "submission_id": packet.docusign_envelope_id},
    ))


@router.post("/webhooks/docuseal")
def docuseal_webhook(
    payload: dict,
    x_docuseal_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not _authorized(x_docuseal_secret, authorization):
        raise HTTPException(401, "Invalid DocuSeal webhook secret")
    submission = _submission(payload)
    packet_id = _packet_id(payload, submission)
    submission_id = submission.get("id") or submission.get("submission_id") or payload.get("submission_id")
    packet = db.get(ContractPacket, packet_id) if packet_id else None
    if not packet and submission_id is not None:
        packet = db.scalar(select(ContractPacket).where(ContractPacket.docusign_envelope_id == str(submission_id)))
    if not packet:
        raise HTTPException(404, "Matching SAHJONY contract packet not found")
    provider_status = _status(payload, submission)
    _apply_status(db, packet, provider_status, payload)
    db.commit()
    return {"accepted": True, "packet_id": packet.id, "status": packet.status, "provider_status": provider_status}


@router.post("/deal-execution/packets/{packet_id}/sync-docuseal")
async def sync_docuseal_packet(
    packet_id: int,
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    packet = db.get(ContractPacket, packet_id)
    if not packet or packet.organization_id != principal.organization_id:
        raise HTTPException(404, "Contract packet not found")
    submission_id = str(packet.docusign_envelope_id or "").strip()
    api_key = str(os.getenv("DOCUSEAL_API_KEY") or "").strip()
    base_url = str(os.getenv("DOCUSEAL_URL") or "").rstrip("/")
    if not submission_id or not api_key or not base_url:
        raise HTTPException(503, "DocuSeal submission, URL, and API key are required")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{base_url}/api/submissions/{submission_id}", headers={"x-auth-token": api_key})
    try:
        data = response.json()
    except ValueError:
        data = {"error": response.text[:1000]}
    if response.status_code >= 400:
        raise HTTPException(502, f"DocuSeal synchronization failed: {data.get('error') or response.status_code}")
    provider_status = _status(data, _submission(data))
    _apply_status(db, packet, provider_status, data)
    db.commit()
    return {"packet_id": packet.id, "status": packet.status, "provider_status": provider_status, "submission_id": submission_id}

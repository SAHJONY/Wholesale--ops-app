from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .database import get_db
from .models import Lead
from .phone_os import HUMAN_TRANSFER, _extract, _score
from .phone_os_pipeline import ensure_next_work, pipeline_snapshot
from .voice_models import VoiceCall

router = APIRouter(prefix="/phone-os/automation", tags=["phone operating system automation"])


def _linked(db: Session, principal: Principal, lead_id: int) -> bool:
    return bool(db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    )))


async def qualify_and_route(db: Session, principal: Principal, call: VoiceCall) -> dict[str, Any]:
    if call.organization_id != principal.organization_id:
        raise HTTPException(404, "Voice call not found")
    transcript = str(call.transcript_excerpt or "").strip()
    if not transcript:
        raise HTTPException(422, "Call has no transcript to qualify")

    evidence = dict(call.evidence or {})
    existing = evidence.get("phone_qualification")
    if isinstance(existing, dict):
        score = {
            "pillars_captured": int(existing.get("pillars_captured") or 0),
            "motivation_score": int(existing.get("motivation_score") or 0),
            "hot_lead": bool(existing.get("hot_lead")),
        }
        pipeline = ensure_next_work(db, principal, call, existing, score)
        db.commit()
        return {
            "call_id": call.id,
            "lead_id": call.lead_id,
            "qualification": existing,
            "score": score,
            "pipeline": pipeline,
            "already_qualified": True,
        }

    if call.lead_id and not _linked(db, principal, call.lead_id):
        raise HTTPException(404, "Linked lead is outside this workspace")

    extracted = await _extract(transcript)
    score = _score(extracted)
    qualification = {
        **extracted,
        **score,
        "facts_are_seller_stated": True,
        "verified_property_facts": False,
        "binding_offer_authority": False,
    }
    evidence["phone_qualification"] = qualification
    call.evidence = evidence

    if call.lead_id:
        lead = db.get(Lead, call.lead_id)
        if lead:
            lead.motivation_score = max(int(lead.motivation_score or 0), int(score["motivation_score"]))
            if extracted.get("timeline_days") is not None:
                lead.timeline_days = int(extracted["timeline_days"])
            if score["hot_lead"] and lead.status not in {"deleted", "closed"}:
                lead.status = "qualified"

    next_action = (
        "Human acquisitions review + source-backed verification/underwriting."
        if score["hot_lead"] else
        "Supervised follow-up; keep seller statements unverified until evidence confirms them."
    )
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        lead_id=call.lead_id,
        activity_type="phone_call_auto_qualified",
        summary=f"Phone OS auto-qualified call #{call.id}: {score['pillars_captured']}/4 pillars, hot={score['hot_lead']}",
        metadata_json={
            "call_id": call.id,
            "qualification": extracted,
            "score": score,
            "next_action": next_action,
            "seller_claims_unverified": True,
        },
    ))
    pipeline = ensure_next_work(db, principal, call, qualification, score)
    db.commit()
    return {
        "call_id": call.id,
        "lead_id": call.lead_id,
        "qualification": qualification,
        "score": score,
        "pipeline": pipeline,
        "next_action": next_action,
        "human_transfer_target": HUMAN_TRANSFER if score["hot_lead"] else None,
        "already_qualified": False,
    }


@router.post("/process-pending")
async def process_pending(
    payload: dict | None = None,
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    limit = max(1, min(25, int((payload or {}).get("limit") or 10)))
    rows = db.scalars(select(VoiceCall).where(
        VoiceCall.organization_id == principal.organization_id,
        VoiceCall.status.in_(["completed", "answered", "ended"]),
        VoiceCall.transcript_excerpt.is_not(None),
    ).order_by(VoiceCall.created_at.desc()).limit(100)).all()

    pending = [row for row in rows if not isinstance((row.evidence or {}).get("phone_qualification"), dict)][:limit]
    results: list[dict[str, Any]] = []
    for call in pending:
        try:
            results.append(await qualify_and_route(db, principal, call))
        except HTTPException as exc:
            db.rollback()
            results.append({"call_id": call.id, "status": "failed", "error": str(exc.detail)})
        except Exception as exc:
            db.rollback()
            results.append({"call_id": call.id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {
        "processed": len(results),
        "results": results,
        "execution_boundary": "qualification_and_work_preparation_only",
        "autonomous_outreach": False,
        "autonomous_offers": False,
        "autonomous_contracts": False,
    }


@router.get("/pipeline")
def pipeline(
    principal: Principal = Depends(require_role("acquisitions")),
    db: Session = Depends(get_db),
):
    return {
        **pipeline_snapshot(db, principal),
        "human_transfer_target": HUMAN_TRANSFER,
        "operating_mode": "supervised_phone_to_deal",
    }

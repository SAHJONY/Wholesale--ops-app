from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth_models import CrmActivity, FollowUpTask
from .database import get_db
from .public_intake import _bot_sink, _consent, _email, _number, _phone, _text, _workspace

router = APIRouter(prefix="/joint-venture-public", tags=["public joint ventures"])


@router.post("")
def submit_joint_venture(payload: dict, db: Session = Depends(get_db)):
    if _bot_sink(payload):
        return {"accepted": True, "reference": "received"}
    if not _consent(payload):
        raise HTTPException(422, "Consent acknowledgment is required")

    organization = _workspace(db)
    name = _text(payload.get("name"), 160)
    company = _text(payload.get("company"), 160)
    email = _email(payload.get("email"))
    phone = _phone(payload.get("phone"))
    address = _text(payload.get("property_address"), 255)
    city = _text(payload.get("city"), 100)
    state = _text(payload.get("state"), 2).upper()
    zip_code = _text(payload.get("zip_code"), 12)
    contract_status = _text(payload.get("contract_status"), 80)
    if not all((name, email, phone, address, city, state, zip_code, contract_status)):
        raise HTTPException(422, "Name, contact information, property location, and contract status are required")

    contract_price = _number(payload.get("contract_price"))
    buyer_price = _number(payload.get("buyer_price"))
    arv = _number(payload.get("arv"))
    repairs = _number(payload.get("repairs"))
    desired_split = _text(payload.get("jv_split"), 80)
    buyer_status = _text(payload.get("buyer_status"), 80)
    timeline = _text(payload.get("timeline"), 160)
    notes = _text(payload.get("notes"), 3000)

    summary = (
        f"JV submission: {address}, {city}, {state} {zip_code}. "
        f"Contract status {contract_status}; contract price {contract_price}; buyer price {buyer_price}; "
        f"ARV {arv}; repairs {repairs}; desired split {desired_split or 'not provided'}; "
        f"buyer status {buyer_status or 'not provided'}."
    )
    activity = CrmActivity(
        organization_id=organization.id,
        activity_type="public_partner_intake",
        summary=summary,
        metadata_json={
            "source": "sahjony.com/joint-venture",
            "name": name,
            "company": company or None,
            "email": email,
            "phone": phone,
            "role": "wholesaler_jv",
            "property_address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "contract_status": contract_status,
            "contract_price": contract_price,
            "buyer_price": buyer_price,
            "arv": arv,
            "repairs": repairs,
            "jv_split": desired_split or None,
            "buyer_status": buyer_status or None,
            "timeline": timeline or None,
            "notes": notes or None,
            "jv_stage": "submitted",
            "communications_consent": True,
            "consent_scope": "respond_to_jv_submission",
            "automated_outreach_authorized": False,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(activity)
    db.flush()
    db.add(FollowUpTask(
        organization_id=organization.id,
        title=f"JV Desk: review submission #{activity.id} — {city}, {state} {zip_code}",
        status="open",
        priority=85,
        notes=(
            "Verify contract/marketing authority, ARV, repairs, contract basis, buyer price, title path, "
            "buyer demand, and written split. Do not infer marketing authority or compensation from intake."
        ),
    ))
    db.commit()
    return {
        "accepted": True,
        "reference": f"jv-{activity.id}",
        "stage": "submitted",
        "next": "jv_desk_review",
    }

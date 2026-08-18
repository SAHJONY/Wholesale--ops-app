from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .crm import _assert_linked
from .database import get_db
from .models import Deal, Lead, Property

router = APIRouter(prefix="/deal-dossier", tags=["deal dossier"])


@router.get("/{deal_id}")
def get_deal_dossier(
    deal_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Return an owner-workspace deal with its property, lead, underwriting and verification context.

    This endpoint intentionally preserves provenance. Scenario values remain in metadata and
    distress evidence instead of being promoted into verified ledger fields such as repairs,
    MAO, contract price, or projected assignment revenue.
    """
    _assert_linked(db, principal, "deal", deal_id)
    deal = db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(404, "Deal not found")

    prop = db.get(Property, deal.property_id)
    if not prop:
        raise HTTPException(422, "Deal is missing its property")
    lead = db.get(Lead, prop.lead_id) if prop.lead_id else None

    metadata = deal.metadata_json or {}
    distress = prop.distress_signals or {}

    return {
        "deal": {
            "id": deal.id,
            "property_id": deal.property_id,
            "stage": deal.stage,
            "strategy": deal.strategy,
            "target_contract_price": deal.target_contract_price,
            "target_buyer_price": deal.target_buyer_price,
            "projected_assignment_fee": deal.projected_assignment_fee,
            "probability_to_close": deal.probability_to_close,
            "risk_score": deal.risk_score,
            "next_action": deal.next_action,
            "metadata": metadata,
        },
        "property": {
            "id": prop.id,
            "lead_id": prop.lead_id,
            "address": prop.address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
            "property_type": prop.property_type,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
            "sqft": prop.sqft,
            "asking_price": prop.asking_price,
            "arv": prop.arv,
            "repairs": prop.repairs,
            "mao": prop.mao,
            "latitude": prop.latitude,
            "longitude": prop.longitude,
            "distress_signals": distress,
        },
        "lead": None if not lead else {
            "id": lead.id,
            "seller_name": lead.seller_name,
            "phone": lead.phone,
            "email": lead.email,
            "source": lead.source,
            "status": lead.status,
            "motivation_score": lead.motivation_score,
            "distress_score": lead.distress_score,
            "equity_score": lead.equity_score,
            "timeline_days": lead.timeline_days,
            "notes": lead.notes,
        },
        "dossier": {
            "auction_date": metadata.get("auction_date") or distress.get("auction_date"),
            "owner_research": metadata.get("owner_research") or distress.get("owner_contact_candidate") or {},
            "deed_research": metadata.get("deed_research") or distress.get("deed_status") or {},
            "communication_gate": metadata.get("communication_gate") or {},
            "hard_blockers": metadata.get("hard_blockers") or [],
            "underwriting": metadata.get("preferred_underwriting_scenario") or {},
            "arv_status": (metadata.get("arv_support") or {}).get("status"),
            "repair_status": metadata.get("repair_status"),
            "buyer_verification": metadata.get("buyer_verification") or {},
            "completion_state": metadata.get("completion_state"),
            "owner_conflict": distress.get("owner_conflict") or {},
            "tax_account": distress.get("tax_account"),
            "parcel_id": distress.get("parcel_id"),
            "legal_description": distress.get("legal_description"),
            "hoa_mandatory": distress.get("hoa_mandatory"),
        },
    }

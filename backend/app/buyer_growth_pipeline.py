from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .auth_models import WorkspaceEntity
from .buyer_match_api import rank_workspace_buyers
from .models import Deal

TERMINAL_DEAL_STAGES = {"closed", "cancelled", "dead", "lost", "archived"}


def disposition_ready_deal_ids(db: Session, principal: Principal) -> list[int]:
    linked = list(db.scalars(select(WorkspaceEntity.entity_id).where(
        WorkspaceEntity.organization_id == principal.organization_id,
        WorkspaceEntity.entity_type == "deal",
    )).all())
    if not linked:
        return []
    deals = db.scalars(select(Deal).where(Deal.id.in_(linked))).all()
    return [
        int(deal.id)
        for deal in deals
        if str(deal.stage or "").lower() not in TERMINAL_DEAL_STAGES
        and (deal.target_buyer_price is not None or deal.target_contract_price is not None)
    ]


def refresh_disposition_matches(db: Session, principal: Principal, limit_per_deal: int = 25) -> dict[str, Any]:
    deal_ids = disposition_ready_deal_ids(db, principal)
    ranked = 0
    total_matches = 0
    errors: list[dict[str, Any]] = []
    for deal_id in deal_ids:
        try:
            result = rank_workspace_buyers(deal_id, {"limit": limit_per_deal}, principal, db)
            ranked += 1
            total_matches += int(result.get("eligible_matches") or 0)
        except Exception as exc:
            db.rollback()
            errors.append({"deal_id": deal_id, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "disposition_ready_deals": len(deal_ids),
        "deals_ranked": ranked,
        "eligible_matches": total_matches,
        "errors": errors,
        "matching_engine": "buying_box_intelligence_v2",
    }

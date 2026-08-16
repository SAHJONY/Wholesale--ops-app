from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .auth_models import CrmActivity, WorkspaceEntity
from .cash_buyer_discovery import aggregate_deeds, deeds_from_rows
from .cash_buyer_models import CashBuyerCandidate
from .models import Buyer

AUTONOMOUS_BUYER_MIN_PURCHASES = 2
AUTONOMOUS_BUYER_MIN_CONFIDENCE = 80.0
DEFAULT_MAX_SOURCES_PER_RUN = 3
DEFAULT_MAX_ROWS_PER_SOURCE = 1000


def _buyer_type(candidate: CashBuyerCandidate) -> str:
    entity_type = str(candidate.entity_type or "").lower()
    if entity_type == "individual_or_unknown":
        return "individual"
    if entity_type in {"llc", "corporation", "partnership", "trust"}:
        return "entity"
    return "private_investor"


def _merge_candidate(db: Session, principal: Principal, entry: dict[str, Any]) -> tuple[CashBuyerCandidate, bool]:
    candidate = db.scalar(select(CashBuyerCandidate).where(
        CashBuyerCandidate.organization_id == principal.organization_id,
        CashBuyerCandidate.normalized_name == entry["normalized_name"],
    ))
    created = candidate is None
    if candidate is None:
        candidate = CashBuyerCandidate(
            organization_id=principal.organization_id,
            status="pending",
            **entry,
        )
        db.add(candidate)
        db.flush()
        return candidate, True

    # A deed-only refresh must never erase stronger mortgage-index evidence from
    # a prior run. Historical cash confirmation is monotonic evidence.
    prior_cash_confirmed = int(candidate.cash_confirmed_count or 0)
    prior_cash_evidence = str(candidate.cash_evidence or "unconfirmed")
    prior_evidence = list(candidate.evidence or [])

    candidate.grantee_name = entry["grantee_name"]
    candidate.entity_type = entry["entity_type"]
    candidate.purchase_count = max(int(candidate.purchase_count or 0), int(entry["purchase_count"] or 0))
    candidate.total_consideration = max(float(candidate.total_consideration or 0), float(entry["total_consideration"] or 0))
    candidate.zip_codes = sorted(set(candidate.zip_codes or []) | set(entry.get("zip_codes") or []))
    candidate.counties = sorted(set(candidate.counties or []) | set(entry.get("counties") or []))
    candidate.first_purchase_at = min(
        [value for value in (candidate.first_purchase_at, entry.get("first_purchase_at")) if value is not None],
        default=None,
    )
    candidate.last_purchase_at = max(
        [value for value in (candidate.last_purchase_at, entry.get("last_purchase_at")) if value is not None],
        default=None,
    )

    incoming_evidence = list(entry.get("evidence") or [])
    seen = {
        (str(row.get("source") or ""), str(row.get("instrument") or ""), str(row.get("parcel") or ""), str(row.get("recorded_at") or ""))
        for row in prior_evidence
    }
    merged_evidence = list(prior_evidence)
    for row in incoming_evidence:
        key = (
            str(row.get("source") or ""),
            str(row.get("instrument") or ""),
            str(row.get("parcel") or ""),
            str(row.get("recorded_at") or ""),
        )
        if key not in seen:
            seen.add(key)
            merged_evidence.append(row)
    candidate.evidence = merged_evidence[-500:]

    incoming_cash_count = int(entry.get("cash_confirmed_count") or 0)
    candidate.cash_confirmed_count = max(prior_cash_confirmed, incoming_cash_count)
    candidate.cash_evidence = "confirmed" if (
        prior_cash_evidence == "confirmed" or incoming_cash_count > 0
    ) else "unconfirmed"

    # Recompute confidence from the strongest stored evidence rather than from
    # a possibly weaker current pull.
    from .cash_buyer_discovery import score_candidate

    candidate.confidence = score_candidate(
        int(candidate.purchase_count or 0),
        str(candidate.entity_type or "individual_or_unknown"),
        int(candidate.cash_confirmed_count or 0),
    )
    return candidate, created


def _auto_promote(db: Session, principal: Principal, candidate: CashBuyerCandidate) -> Buyer | None:
    if candidate.promoted_buyer_id:
        return db.get(Buyer, candidate.promoted_buyer_id)
    if int(candidate.purchase_count or 0) < AUTONOMOUS_BUYER_MIN_PURCHASES:
        return None
    if float(candidate.confidence or 0) < AUTONOMOUS_BUYER_MIN_CONFIDENCE:
        return None
    if str(candidate.cash_evidence or "") != "confirmed" or int(candidate.cash_confirmed_count or 0) < 1:
        return None

    buyer = Buyer(
        name=candidate.grantee_name,
        company=candidate.grantee_name if candidate.entity_type != "individual_or_unknown" else None,
        buyer_type=_buyer_type(candidate),
        # Recorded deeds do not contain a callable contact. Empty keeps the
        # evidence-backed buyer in the registry without inventing a phone.
        phone="",
        email=None,
        zip_codes=list(candidate.zip_codes or []),
        asset_types=["single_family"],
        # Historical cash purchases are not current proof of funds.
        proof_of_funds_verified=False,
        reliability_score=min(95.0, float(candidate.confidence or 0)),
    )
    db.add(buyer)
    db.flush()
    db.add(WorkspaceEntity(
        organization_id=principal.organization_id,
        entity_type="buyer",
        entity_id=buyer.id,
    ))
    candidate.promoted_buyer_id = buyer.id
    candidate.status = "approved"
    candidate.reviewed_by_user_id = principal.user_id
    candidate.reviewed_at = datetime.now(timezone.utc)
    candidate.reviewer_notes = (
        "Autonomously promoted from repeated recorded purchases with explicit historical cash evidence. "
        "No contact data inferred; current proof of funds remains unverified."
    )
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="cash_buyer_autonomously_promoted",
        summary=f"Evidence-backed cash buyer '{candidate.grantee_name}' added to buyer registry",
        metadata_json={
            "candidate_id": candidate.id,
            "buyer_id": buyer.id,
            "purchase_count": candidate.purchase_count,
            "cash_confirmed_count": candidate.cash_confirmed_count,
            "confidence": candidate.confidence,
            "contact_status": "not_on_file",
            "proof_of_funds_current": False,
        },
    ))
    return buyer


async def run_autonomous_cash_buyer_intelligence(
    db: Session,
    principal: Principal,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES_PER_RUN,
    max_rows: int = DEFAULT_MAX_ROWS_PER_SOURCE,
) -> dict[str, Any]:
    """Continuously discover deed-backed buyer candidates and safely promote only verified cash patterns."""
    from .distress_ingest import fetch_rows, load_jurisdictions

    sources = sorted(
        [source for source in load_jurisdictions() if source.category == "cash_purchase_deed"],
        key=lambda source: source.id,
    )
    if not sources:
        return {
            "organization_id": principal.organization_id,
            "status": "no_sources",
            "sources_configured": 0,
            "candidates_created": 0,
            "candidates_updated": 0,
            "buyers_promoted": 0,
            "boundary": "Configure public cash_purchase_deed jurisdiction feeds before autonomous discovery can run.",
        }

    max_sources = max(1, min(int(max_sources or DEFAULT_MAX_SOURCES_PER_RUN), 10, len(sources)))
    max_rows = max(1, min(int(max_rows or DEFAULT_MAX_ROWS_PER_SOURCE), 5000))

    # Deterministic 15-minute rotation distributes nationwide coverage without
    # trying to enumerate every county inside one serverless invocation.
    slot = int(datetime.now(timezone.utc).timestamp()) // 900
    start = slot % len(sources)
    selected = [sources[(start + offset) % len(sources)] for offset in range(max_sources)]

    created = updated = promoted = rows_read = 0
    source_results: list[dict[str, Any]] = []
    for source in selected:
        rows = await fetch_rows(source, max_rows)
        rows_read += len(rows)
        aggregated = aggregate_deeds(deeds_from_rows(source, rows, liens=None))
        source_created = source_updated = source_promoted = 0
        for entry in aggregated:
            candidate, was_created = _merge_candidate(db, principal, entry)
            if was_created:
                created += 1
                source_created += 1
            else:
                updated += 1
                source_updated += 1
            if _auto_promote(db, principal, candidate):
                promoted += 1
                source_promoted += 1
        db.commit()
        source_results.append({
            "source_id": source.id,
            "county": source.county,
            "state": source.state,
            "rows_read": len(rows),
            "truncated": len(rows) >= max_rows,
            "candidates_created": source_created,
            "candidates_updated": source_updated,
            "buyers_promoted": source_promoted,
        })

    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type="autonomous_cash_buyer_intelligence_cycle",
        summary=f"Cash Buyer Intelligence scanned {len(selected)} deed sources and promoted {promoted} verified buyers",
        metadata_json={
            "sources_configured": len(sources),
            "sources_scanned": [source.id for source in selected],
            "rows_read": rows_read,
            "candidates_created": created,
            "candidates_updated": updated,
            "buyers_promoted": promoted,
            "schedule": "15_minute_rotation",
        },
    ))
    db.commit()

    return {
        "organization_id": principal.organization_id,
        "status": "completed",
        "sources_configured": len(sources),
        "sources_scanned": len(selected),
        "rows_read": rows_read,
        "candidates_created": created,
        "candidates_updated": updated,
        "buyers_promoted": promoted,
        "source_results": source_results,
        "autonomy_boundary": {
            "buyer_registry_write": "allowed_only_for_repeated_purchases_with_explicit_historical_cash_evidence",
            "contact_inference": False,
            "current_pof_inference": False,
            "outreach_dispatch": False,
        },
    }

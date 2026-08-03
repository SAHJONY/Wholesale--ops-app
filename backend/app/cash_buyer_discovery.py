"""Find cash buyers in recorded deeds instead of guessing from adverts.

The common way to build a buyer list is to read rental and flip listings and
infer who owns them. That inverts the evidence: a listing saying "recently
renovated" is a guess about ownership, while a recorded deed states who took
title, on what date, for what consideration. One is a description, the other is
the county's record of the transaction.

So buyers are discovered from deeds. Three things follow from that choice:

**A deed does not prove cash.** It proves a transfer. Proving cash means
searching the mortgage index for the same parcel and finding nothing recorded
against it, which is a second dataset. Where that search has not happened the
candidate is reported ``cash_evidence="unconfirmed"``, never quietly upgraded.
Calling a financed purchase a cash purchase would put a buyer on a call list
under a claim the record does not support.

**Repetition is the signal, not entity type.** An LLC in the grantee field
suggests a business rather than an owner-occupant, but plenty of families hold
a home in a trust. What distinguishes an investor is buying repeatedly, and
that is counted from records rather than inferred from a name.

**Nothing becomes a buyer without a human.** Candidates land in a review queue
with their evidence attached and are promoted by an owner or manager, matching
how county ownership verification already works. A discovered name joining the
buyer list on its own would put outreach in front of someone no one chose.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal, require_role
from .auth_models import CrmActivity, WorkspaceEntity
from .cash_buyer_models import CashBuyerCandidate
from .database import get_db
from .models import Buyer

router = APIRouter(prefix="/cash-buyers", tags=["cash buyer discovery"])

# Suffixes dropped when comparing names, so one entity is not counted twice for
# punctuating itself differently.
ENTITY_SUFFIXES = (
    "llc", "l l c", "inc", "incorporated", "corp", "corporation", "co",
    "lp", "llp", "lllp", "ltd", "limited", "trust", "tr", "company",
)

ENTITY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("llc", ("llc", "l.l.c", "l l c", "limited liability")),
    ("corporation", ("inc", "incorporated", "corp", "corporation")),
    ("partnership", ("lp", "llp", "lllp", "partners", "partnership")),
    ("trust", ("trust", " tr ", "trustee")),
)

# Promotion threshold, matching the county verification queue's bar.
MIN_CONFIDENCE_TO_PROMOTE = 80.0


def normalize_name(raw: str) -> str:
    """A comparable form of a recorded name.

    Recorders are inconsistent about punctuation and suffixes, so
    "APEX PROPERTIES, L.L.C." and "Apex Properties LLC" must land on the same
    candidate or one investor becomes several.
    """
    text = re.sub(r"[^a-z0-9 ]+", " ", (raw or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in sorted(ENTITY_SUFFIXES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(suffix)}\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_entity(raw: str) -> str:
    haystack = f" {(raw or '').lower()} "
    for entity_type, markers in ENTITY_MARKERS:
        if any(marker in haystack for marker in markers):
            return entity_type
    return "individual_or_unknown"


def score_candidate(
    purchase_count: int,
    entity_type: str,
    cash_confirmed_count: int,
) -> float:
    """How strongly the records support "this is an active cash buyer".

    Deliberately weighted toward counted facts. A single recorded purchase is
    real but weak evidence of an ongoing buyer; repetition is what makes the
    pattern, and a confirmed absence of financing is the only thing that earns
    the word cash.
    """
    if purchase_count <= 0:
        return 0.0
    score = 40.0
    score += min(30.0, (purchase_count - 1) * 15.0)
    if entity_type != "individual_or_unknown":
        score += 10.0
    if cash_confirmed_count > 0:
        score += 15.0
    # Never 100: the records show past purchases, not a commitment to buy again.
    return min(95.0, round(score, 1))


def _as_float(value: Any) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:19] if "T" in text else text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def aggregate_deeds(deeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group recorded transfers into one candidate per grantee.

    Rows without a grantee are dropped rather than bucketed under a blank name:
    a deed whose buyer cannot be read is not evidence of anybody.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for deed in deeds:
        raw_name = str(deed.get("grantee") or "").strip()
        key = normalize_name(raw_name)
        if not key:
            continue

        recorded_at = _as_datetime(deed.get("recorded_at"))
        consideration = _as_float(deed.get("consideration"))
        # A mortgage search that did not happen is not a search that found
        # nothing, so only an explicit False counts as confirmation.
        confirmed = deed.get("mortgage_found") is False

        entry = grouped.setdefault(key, {
            "grantee_name": raw_name,
            "normalized_name": key,
            "entity_type": classify_entity(raw_name),
            "purchase_count": 0,
            "total_consideration": 0.0,
            "cash_confirmed_count": 0,
            "first_purchase_at": None,
            "last_purchase_at": None,
            "zip_codes": [],
            "counties": [],
            "evidence": [],
        })
        entry["purchase_count"] += 1
        entry["total_consideration"] += consideration
        if confirmed:
            entry["cash_confirmed_count"] += 1
        if recorded_at:
            if not entry["first_purchase_at"] or recorded_at < entry["first_purchase_at"]:
                entry["first_purchase_at"] = recorded_at
            if not entry["last_purchase_at"] or recorded_at > entry["last_purchase_at"]:
                entry["last_purchase_at"] = recorded_at
        for field, bucket in (("zip_code", "zip_codes"), ("county", "counties")):
            value = str(deed.get(field) or "").strip()
            if value and value not in entry[bucket]:
                entry[bucket].append(value)
        entry["evidence"].append({
            "instrument": deed.get("instrument"),
            "parcel": deed.get("parcel"),
            "address": deed.get("address"),
            "recorded_at": recorded_at.isoformat() if recorded_at else None,
            "consideration": consideration or None,
            "mortgage_index_searched": deed.get("mortgage_found") is not None,
            "source": deed.get("source"),
        })

    for entry in grouped.values():
        entry["cash_evidence"] = "confirmed" if entry["cash_confirmed_count"] else "unconfirmed"
        entry["confidence"] = score_candidate(
            entry["purchase_count"], entry["entity_type"], entry["cash_confirmed_count"]
        )
    return sorted(grouped.values(), key=lambda e: (-e["confidence"], -e["purchase_count"]))


@router.post("/ingest-deeds")
def ingest_deeds(
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Turn recorded transfers into reviewable candidates. Creates no buyers."""
    deeds = payload.get("deeds")
    if not isinstance(deeds, list) or not deeds:
        raise HTTPException(422, "deeds must be a non-empty list of recorded transfers")

    created = updated = 0
    for entry in aggregate_deeds(deeds):
        candidate = db.scalar(select(CashBuyerCandidate).where(
            CashBuyerCandidate.organization_id == principal.organization_id,
            CashBuyerCandidate.normalized_name == entry["normalized_name"],
        ))
        if candidate:
            # Re-running a sweep must not double-count; the aggregate replaces
            # rather than accumulates, and a reviewed candidate keeps its state.
            for field in (
                "grantee_name", "entity_type", "purchase_count", "total_consideration",
                "cash_confirmed_count", "cash_evidence", "confidence", "zip_codes",
                "counties", "evidence", "first_purchase_at", "last_purchase_at",
            ):
                setattr(candidate, field, entry[field])
            updated += 1
        else:
            db.add(CashBuyerCandidate(
                organization_id=principal.organization_id, status="pending", **entry
            ))
            created += 1
    db.commit()
    return {
        "organization_id": principal.organization_id,
        "deeds_received": len(deeds),
        "candidates_created": created,
        "candidates_updated": updated,
        "note": (
            "Candidates only. Nothing here is a buyer until an owner or manager promotes it, "
            "and cash_evidence stays 'unconfirmed' unless a mortgage search reported no lien."
        ),
    }


@router.get("/candidates")
def candidates(
    status: str | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    query = select(CashBuyerCandidate).where(
        CashBuyerCandidate.organization_id == principal.organization_id
    )
    if status:
        query = query.where(CashBuyerCandidate.status == status)
    rows = db.scalars(query.order_by(CashBuyerCandidate.confidence.desc())).all()
    counts = dict(db.execute(
        select(CashBuyerCandidate.status, func.count(CashBuyerCandidate.id))
        .where(CashBuyerCandidate.organization_id == principal.organization_id)
        .group_by(CashBuyerCandidate.status)
    ).all())
    return {
        "organization_id": principal.organization_id,
        "summary": {
            "by_status": counts,
            "cash_confirmed": sum(1 for r in rows if r.cash_evidence == "confirmed"),
            "promotable": sum(
                1 for r in rows
                if r.status == "pending" and r.confidence >= MIN_CONFIDENCE_TO_PROMOTE
            ),
        },
        "candidates": [{
            "id": r.id,
            "grantee_name": r.grantee_name,
            "entity_type": r.entity_type,
            "status": r.status,
            "confidence": r.confidence,
            "purchase_count": r.purchase_count,
            "total_consideration": r.total_consideration,
            "cash_evidence": r.cash_evidence,
            "cash_confirmed_count": r.cash_confirmed_count,
            "zip_codes": r.zip_codes,
            "counties": r.counties,
            "last_purchase_at": r.last_purchase_at,
            "promoted_buyer_id": r.promoted_buyer_id,
            "evidence": r.evidence,
        } for r in rows],
        "promotion_threshold": MIN_CONFIDENCE_TO_PROMOTE,
    }


@router.post("/candidates/{candidate_id}/decision")
def decide(
    candidate_id: int,
    payload: dict[str, Any],
    principal: Principal = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    """Approve, reject, or hold a candidate. Approval creates the buyer."""
    candidate = db.scalar(select(CashBuyerCandidate).where(
        CashBuyerCandidate.id == candidate_id,
        CashBuyerCandidate.organization_id == principal.organization_id,
    ))
    if not candidate:
        raise HTTPException(404, "Cash buyer candidate not found")

    decision = str(payload.get("decision") or "").lower()
    if decision not in {"approved", "rejected", "needs_review"}:
        raise HTTPException(422, "Decision must be approved, rejected, or needs_review")

    if decision == "approved":
        if candidate.promoted_buyer_id:
            raise HTTPException(409, f"Already promoted to buyer #{candidate.promoted_buyer_id}")
        if candidate.confidence < MIN_CONFIDENCE_TO_PROMOTE:
            raise HTTPException(
                422,
                f"Confidence {candidate.confidence} is below {MIN_CONFIDENCE_TO_PROMOTE}. "
                "One recorded purchase is not evidence of an active buyer.",
            )
        phone = str(payload.get("phone") or "").strip()
        if not phone:
            # Deeds carry no contact details. Requiring one here keeps the
            # buyer list callable and keeps the gap visible rather than
            # creating a record nobody can act on.
            raise HTTPException(
                422,
                "A phone number is required to promote. Recorded deeds carry no contact "
                "details, so supply one from your own research or skip-tracing.",
            )
        buyer = Buyer(
            name=candidate.grantee_name,
            company=candidate.grantee_name if candidate.entity_type != "individual_or_unknown" else None,
            buyer_type=str(payload.get("buyer_type") or "cash_buyer"),
            phone=phone,
            email=str(payload.get("email") or "").strip() or None,
            zip_codes=list(candidate.zip_codes or []),
            # A deed proves the money existed for that purchase, not that funds
            # are available now. Only a confirmed cash record starts this true.
            proof_of_funds_verified=candidate.cash_evidence == "confirmed",
        )
        db.add(buyer)
        db.flush()
        db.add(WorkspaceEntity(
            organization_id=principal.organization_id, entity_type="buyer", entity_id=buyer.id
        ))
        candidate.promoted_buyer_id = buyer.id

    candidate.status = decision
    candidate.reviewed_by_user_id = principal.user_id
    candidate.reviewed_at = datetime.now(timezone.utc)
    candidate.reviewer_notes = str(payload.get("reviewer_notes") or candidate.reviewer_notes or "") or None
    db.add(CrmActivity(
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        activity_type=f"cash_buyer_candidate_{decision}",
        summary=f"Cash buyer candidate '{candidate.grantee_name}' marked {decision}",
        metadata_json={
            "candidate_id": candidate.id,
            "confidence": candidate.confidence,
            "purchase_count": candidate.purchase_count,
            "cash_evidence": candidate.cash_evidence,
            "promoted_buyer_id": candidate.promoted_buyer_id,
        },
    ))
    db.commit()
    return {
        "candidate_id": candidate.id,
        "status": candidate.status,
        "promoted_buyer_id": candidate.promoted_buyer_id,
        "reviewed_at": candidate.reviewed_at,
    }

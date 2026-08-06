"""List stacking: how many independent distress signals land on one property.

This is the feature the commercial lead platforms are actually selling. One
tax-delinquent property is a lead. A property that is tax delinquent *and* has
an open code violation *and* sits in probate is a different animal: three
county offices independently recorded that something is wrong with it, and the
owner is carrying three problems at once. Conversion rates on stacked lists are
not marginally better than single-signal lists, they are the reason the lists
are worth buying.

Nothing here calls an external provider. It reads ``intelligence_facts``, which
already records which source established which field on which property, so the
stack is computed from evidence the system has already verified and stored.
That also means it works today, without any of the credentials the rest of the
pipeline is waiting on.

Two rules keep it honest:

* **A signal counts only when a source asserted it is true.** ``intelligence_facts``
  stores what a source said, and a source can say ``tax_delinquent: false``. A
  naive existence check would score that as distress and inflate every property
  that has ever been looked at.
* **No signals is "nothing established", never "not distressed."** A property
  nobody has pulled records for looks identical to a clean one, and the
  response says which it is rather than implying the stronger claim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import listing_language
from .auth import Principal, get_principal
from .database import get_db
from .distress_providers import PROVIDERS
from .intelligence_models import IntelligenceFact
from .models import Property

router = APIRouter(prefix="/leads/stacking", tags=["list stacking"])

# The one field per source whose truth establishes that source's signal. Named
# explicitly rather than taken as writable_fields[0]: the tuple order is a
# readability choice in the provider spec, and silently depending on it would
# turn a cosmetic reordering into a scoring change.
SIGNAL_FIELDS: dict[str, str] = {
    "tax_delinquency": "tax_delinquent",
    "code_violation": "code_violation_open",
    "probate": "probate_case_open",
    "lis_pendens": "lis_pendens_filed",
    "notice_of_default": "notice_of_default_recorded",
    "notice_of_trustee_sale": "trustee_sale_scheduled",
    "foreclosure_sale": "foreclosure_sale_scheduled",
    "demolition_permit": "demolition_permit_open",
    # USPS-derived, via Smarty. Not a county office like the others, but the
    # same kind of claim: a named authority recorded a condition on the parcel.
    "usps_vacancy": "usps_reported_vacant",
}

# Only distress sources stack. A listing or a cash-purchase deed says something
# useful about a property but it is not a reason the owner might sell cheaply,
# and mixing them would make the count mean two different things at once.
DISTRESS_SOURCES = frozenset(
    p.id for p in PROVIDERS if p.category == "distress" and p.id in SIGNAL_FIELDS
)

# Conviction bands. Three independent county offices recording problems on the
# same parcel is the threshold the desk should be working first.
TIERS = ((3, "high_conviction"), (2, "stacked"), (1, "single_signal"))


def _is_asserted(value: Any) -> bool:
    """Whether a stored fact actually asserts the signal.

    ``value_json`` holds whatever the source said. ``False``, ``None``, empty
    string and ``0`` are all a source reporting the *absence* of the condition,
    which is a useful fact and not a distress signal.
    """
    if isinstance(value, dict):
        value = value.get("value", value)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "no", "0", "none", "null"}
    return bool(value)


def _tier(count: int) -> str:
    for threshold, name in TIERS:
        if count >= threshold:
            return name
    return "none"


def stack_for_facts(facts: list[IntelligenceFact], now: datetime) -> dict[str, Any]:
    """Reduce one property's facts to a stack.

    Deliberately takes facts rather than a property id so the scoring is a pure
    function that tests can drive directly, without a database round trip
    standing between the input and the number.
    """
    signals: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if fact.source not in DISTRESS_SOURCES:
            continue
        if SIGNAL_FIELDS.get(fact.source) != fact.field_name:
            continue
        # An expired fact is a fact that was true once. Counting it would let a
        # cleared code violation keep a property near the top of the list.
        if fact.expires_at is not None and fact.expires_at <= now:
            continue
        if not _is_asserted(fact.value_json):
            continue

        existing = signals.get(fact.source)
        if existing is None or (fact.confidence or 0) > existing["confidence"]:
            signals[fact.source] = {
                "source": fact.source,
                "field": fact.field_name,
                "confidence": fact.confidence or 0,
                "verification_status": fact.verification_status,
                "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
                "source_reference": fact.source_reference,
            }

    ordered = sorted(signals.values(), key=lambda s: -s["confidence"])
    verified = [s for s in ordered if s["verification_status"] == "verified"]
    return {
        "signal_count": len(ordered),
        "verified_signal_count": len(verified),
        # The count is the number that matters; this only breaks ties between
        # properties carrying the same number of signals.
        "confidence_weight": round(sum(s["confidence"] for s in ordered), 1),
        "tier": _tier(len(ordered)),
        "signals": ordered,
        "note": (
            "No distress signal has been established for this property. That is an "
            "absence of records pulled, not evidence the property is unencumbered."
            if not ordered else
            f"{len(ordered)} independent source(s) recorded a distress condition."
        ),
    }


def _facts_by_property(db: Session, organization_id: int) -> dict[int, list[IntelligenceFact]]:
    rows = db.scalars(
        select(IntelligenceFact).where(
            IntelligenceFact.organization_id == organization_id,
            IntelligenceFact.entity_type == "property",
            IntelligenceFact.source.in_(DISTRESS_SOURCES),
        )
    ).all()
    grouped: dict[int, list[IntelligenceFact]] = {}
    for row in rows:
        grouped.setdefault(row.entity_id, []).append(row)
    return grouped


@router.get("")
def stacked_leads(
    min_signals: int = Query(2, ge=1, le=len(SIGNAL_FIELDS)),
    limit: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Properties ranked by how many independent sources flagged them.

    Defaults to ``min_signals=2`` because a single-signal list is just the
    underlying feed, which the distress endpoints already serve.
    """
    now = datetime.now(timezone.utc)
    grouped = _facts_by_property(db, principal.organization_id)

    scored = []
    for property_id, facts in grouped.items():
        stack = stack_for_facts(facts, now)
        if stack["signal_count"] >= min_signals:
            scored.append((property_id, stack))

    scored.sort(key=lambda item: (-item[1]["signal_count"], -item[1]["confidence_weight"]))
    top = scored[:limit]

    properties = {
        p.id: p
        for p in db.scalars(
            select(Property).where(Property.id.in_([pid for pid, _ in top]))
        ).all()
    } if top else {}

    return {
        "organization_id": principal.organization_id,
        "min_signals": min_signals,
        "returned": len(top),
        "properties_with_any_signal": len(grouped),
        "leads": [
            {
                "property_id": property_id,
                "address": getattr(properties.get(property_id), "address", None),
                **stack,
            }
            for property_id, stack in top
        ],
        "advisory": (
            "Ranking reflects how many sources recorded a condition, not how likely the "
            "owner is to sell. Every lead still passes lead verification and owner "
            "approval before any outreach."
        ),
    }


@router.get("/property/{property_id}")
def property_stack(
    property_id: int,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """The stack for one property, with each signal's originating source."""
    facts = db.scalars(
        select(IntelligenceFact).where(
            IntelligenceFact.organization_id == principal.organization_id,
            IntelligenceFact.entity_type == "property",
            IntelligenceFact.entity_id == property_id,
        )
    ).all()
    now = datetime.now(timezone.utc)
    facts = list(facts)
    return {
        "property_id": property_id,
        **stack_for_facts(facts, now),
        # Reported beside the stack, never folded into it. Agent-authored
        # marketing copy and a county filing are different kinds of evidence,
        # and a single number covering both would mean neither.
        "listing_language": listing_language.scan_facts(facts, now),
    }


@router.get("/sources")
def stackable_sources(principal: Principal = Depends(get_principal)):
    """Which sources can contribute a signal, and which field establishes it."""
    return {
        "organization_id": principal.organization_id,
        "sources": [
            {"source": source, "signal_field": SIGNAL_FIELDS[source]}
            for source in sorted(DISTRESS_SOURCES)
        ],
        "tiers": [{"min_signals": n, "tier": name} for n, name in TIERS],
    }

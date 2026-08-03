"""Which office holds a foreclosure record, and therefore where to look.

Foreclosure runs on one of two tracks, and the track decides which authority
creates the record:

* **Judicial.** The lender sues. The case lives with the district or circuit
  court, and the public artefacts are the lis pendens recorded against the
  parcel, the complaint and judgment on the court docket, and a sheriff's sale
  at the end.
* **Non-judicial.** A power-of-sale clause lets a trustee proceed without a
  lawsuit. There is no docket. The artefacts are a Notice of Default and a
  Notice of Trustee Sale, recorded with the county recorder or published by the
  substitute trustee inside a statutory window.

Collapsing the two, as this system did before, makes a jurisdiction impossible
to configure correctly: pointing a "foreclosure" feed at a court docket in a
non-judicial state finds nothing, and the emptiness looks like an absence of
distress rather than a misconfiguration.

## What the table below is, and is not

``STATE_PROCEDURE`` is **routing guidance**. It answers "which county office
should I be asking?" so an operator does not configure a court endpoint in a
trustee state. It is deliberately not wired to any writable field on a
property, and no fact derived from it may reach a lead.

It is not legal advice and not a determination about any parcel. Several states
permit both tracks, lenders choose per loan, and statutes change. Where a
configured jurisdiction declares its own procedure, that declaration wins:
observation beats a lookup table.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .auth import Principal, get_principal

router = APIRouter(prefix="/foreclosure-procedure", tags=["foreclosure procedure"])

JUDICIAL = "judicial"
NON_JUDICIAL = "non_judicial"
BOTH = "both"
UNKNOWN = "unknown"

PROCEDURES = (JUDICIAL, NON_JUDICIAL, BOTH)

# Prevailing practice per state. "both" marks states where either track is
# routinely used, so an operator should expect records in more than one office.
STATE_PROCEDURE: dict[str, str] = {
    # Lender must sue; look to the court docket and the recorded lis pendens.
    **{s: JUDICIAL for s in (
        "CT", "DE", "FL", "IL", "IN", "KS", "KY", "LA", "ME", "ND",
        "NJ", "NM", "NY", "OH", "PA", "SC", "VT", "WI",
    )},
    # Power of sale; look to the recorder and the substitute trustee.
    **{s: NON_JUDICIAL for s in (
        "AK", "AZ", "AR", "CA", "CO", "DC", "GA", "ID", "MD", "MI",
        "MN", "MS", "MO", "MT", "NV", "NH", "NC", "OR", "TN", "UT",
        "VA", "WA", "WV", "WY",
    )},
    # Either track is ordinary practice; expect both offices to hold records.
    **{s: BOTH for s in ("AL", "HI", "IA", "MA", "NE", "OK", "RI", "SD")},
}

# Where each track's records are created, which is what an operator needs in
# order to point a jurisdiction entry at the right endpoint.
TRACK_OFFICES: dict[str, dict[str, object]] = {
    JUDICIAL: {
        "offices": ["district_or_circuit_court", "county_recorder", "county_sheriff"],
        "expect_documents": ["lis_pendens", "foreclosure_complaint", "judgment", "sheriff_sale_notice"],
        "categories": ["lis_pendens", "foreclosure_sale"],
    },
    NON_JUDICIAL: {
        "offices": ["county_recorder", "substitute_trustee"],
        "expect_documents": ["notice_of_default", "notice_of_trustee_sale"],
        "categories": ["notice_of_default", "notice_of_trustee_sale", "foreclosure_sale"],
    },
}


def procedure_for_state(state: str | None) -> str:
    """Prevailing track for a state, or ``unknown`` when it is not in the table."""
    return STATE_PROCEDURE.get((state or "").strip().upper(), UNKNOWN)


def tracks_for_state(state: str | None) -> list[str]:
    """Tracks whose records are worth searching in a state.

    ``both`` and ``unknown`` widen to every track rather than picking one: a
    guess that narrows the search is how a real filing gets missed, and an
    unlisted state is a gap in the table, not evidence about the state.
    """
    procedure = procedure_for_state(state)
    if procedure in (BOTH, UNKNOWN):
        return [JUDICIAL, NON_JUDICIAL]
    return [procedure]


def guidance(state: str | None) -> dict[str, object]:
    normalized = (state or "").strip().upper()
    procedure = procedure_for_state(normalized)
    tracks = tracks_for_state(normalized)
    return {
        "state": normalized or None,
        "procedure": procedure,
        "search_tracks": tracks,
        "offices": sorted({o for t in tracks for o in TRACK_OFFICES[t]["offices"]}),
        "expect_documents": sorted({d for t in tracks for d in TRACK_OFFICES[t]["expect_documents"]}),
        "categories": sorted({c for t in tracks for c in TRACK_OFFICES[t]["categories"]}),
        "advisory": (
            "Routing guidance for locating records, not a determination about any property "
            "and not legal advice. Many states permit both tracks and lenders choose per loan. "
            "A jurisdiction entry that declares its own procedure overrides this."
        ),
    }


@router.get("/states")
def states(principal: Principal = Depends(get_principal)):
    """The full table, so an operator can see the gaps rather than guess at them."""
    return {
        "organization_id": principal.organization_id,
        "procedures": PROCEDURES,
        "states": {state: procedure_for_state(state) for state in sorted(STATE_PROCEDURE)},
        "tracks": TRACK_OFFICES,
        "advisory": (
            "Routing guidance only. Texas is excluded from this workflow elsewhere in the "
            "system and is deliberately absent from this table."
        ),
    }


@router.get("/states/{state}")
def state_detail(state: str, principal: Principal = Depends(get_principal)):
    return {"organization_id": principal.organization_id, **guidance(state)}

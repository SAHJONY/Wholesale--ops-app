# SAHJONY Universal Property Intake Standard

## Purpose
Every property entering SAHJONY Wholesale OS must be converted into a governed, evidence-tracked opportunity rather than a bare address or seller lead.

## Mandatory Intake State
For every property, regardless of source (foreclosure, tax delinquency, probate, code violation, CSV, FSBO, MLS/on-market, Facebook, driving-for-dollars, vacant land, autonomous discovery, or manual entry), create or reconcile:

1. Lead record.
2. Property record with complete address when available.
3. Workspace links.
4. Source provenance.
5. Property identity verification state.
6. Owner-resolution task.
7. Official owner-record gate or property-address fallback.
8. Contact cross-verification gate.
9. Contact Ready state distinct from outreach authorization.
10. Underwriting evidence state.
11. Buyer verification state.
12. Compliance/outreach state.

## Property Identity
Capture when available:
- street address
- city/state/ZIP
- county
- APN/tax account
- legal description
- beds/baths/sqft
- year built/property type
- source URL/provider
- retrieval timestamp
- foreclosure/auction/distress evidence

Missing APN or legal description must remain explicitly unresolved; never invent them.

## Owner Resolution
Preferred sequence:
1. County assessor/appraisal district.
2. Recorder/clerk/deed record.
3. County tax/government open data.
4. Authorized licensed provider.
5. If owner-of-record remains unavailable, use full property address as the lookup seed.
6. Manual-assisted public people-search evidence may identify candidates, but cannot by itself verify ownership.

## Contact Gate
A contact candidate is separate from owner verification.

- If owner-of-record is verified: require matching contact evidence from at least two independent sources and >=80 confidence.
- If using address-seeded fallback: require the same phone/email from at least two independent sources and >=90 confidence.
- Contact Ready never means outreach authorized.

## Underwriting
SFR follows SAHJONY 70% rule only after adequate ARV/repair evidence:
- MAO = ARV × 0.70 − Repairs − Assignment Fee
- Opening Offer = MAO × 0.85
- Hard Walkaway = MAO

Vacant land uses a separate land underwriting model and must not inherit SFR repair assumptions.

## Buyer Gate
Do not mark a buyer deal-ready until:
- buying box confirmed
- deal/ZIP fit confirmed
- assignment acceptance confirmed where applicable
- POF verified
- closing timeline confirmed

## Compliance Gate
No automated seller outreach merely because a phone or email was found. Preserve DNC/TCPA/state/company policy gates and any approval requirements.

## Self-Healing Enforcement
`POST /self-healing/enforce-property-standard` checks the workspace and creates a missing `owner_resolution` task for every active property.

Every `POST /self-healing/scan` also runs this structural enforcement before diagnosing individual task failures.

The enforcement is idempotent: a property with an existing owner-resolution task is not duplicated.

## Core Rule
A property may enter the application with unresolved fields, but it may not enter without a defined verification path. Missing evidence becomes a task and blocker, never an invented fact.
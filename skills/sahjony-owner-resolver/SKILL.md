# SAHJONY Autonomous Owner Resolver

## Purpose
Resolve property ownership and contact candidates for wholesale acquisition without inventing identity data or bypassing access controls.

## Source cascade
1. County assessor / property appraiser / recorder / clerk records: establish parcel, situs address, owner-of-record, mailing address, deed evidence, tax/distress facts.
2. Existing authorized property-data providers in Wholesale OS: enrich parcel/property characteristics and ownership evidence.
3. Public people-search sources, including CyberBackgroundChecks and TruePeopleSearch, may be used only as manual-assisted public resolvers unless SAHJONY has an authorized API or licensed integration.
4. Commercial enrichment providers with documented API rights may be called when configured.

## TruePeopleSearch policy
- Source: https://www.truepeoplesearch.com/
- Mode: manual_assisted_public_resolver
- No public API is assumed.
- Do not evade Cloudflare, CAPTCHA, geofencing, rate limits, login, robots/access controls, or other anti-automation mechanisms.
- The system may prepare a normalized lookup packet: owner name, mailing address, property address, city, state, ZIP.
- A human or authorized browser workflow may enter results back into the system with source URL and retrieval timestamp.

## CyberBackgroundChecks policy
- Source: https://www.cyberbackgroundchecks.com/
- Mode: manual_assisted_public_resolver unless an authorized API becomes available.
- Same non-bypass and provenance requirements as TruePeopleSearch.

## Resolution output
Every candidate contact must include:
- owner_of_record_name
- property_address
- owner_mailing_address when available
- candidate_phone and/or candidate_email when lawfully sourced
- source_name
- source_url or provider evidence identifier
- retrieved_at
- identity_match_confidence: 0-100
- evidence_notes
- status: unverified | likely | cross_verified | contact_ready

## Confidence rules
- County owner record alone verifies ownership, not phone/email.
- A people-search result matching only a common name is never contact_ready.
- Matching owner name + mailing city/state: at most likely.
- Matching owner name + exact mailing address: stronger evidence.
- A contact becomes cross_verified only after corroboration by a second independent source or an authorized enrichment provider.
- Never infer phone ownership, email ownership, DNC status, consent, or proof of identity.

## Compliance gates
Contact resolution is separate from outreach authorization. Before automated SMS/calls, downstream systems must enforce applicable consent/DNC/TCPA/state rules, organizational authority, and existing SAHJONY outbound gates. Public-record availability alone is not consent to automated marketing.

## Operating objective
Produce traceable owner/contact intelligence for high-priority distressed properties while failing closed on ambiguous identity matches and preserving a complete evidence trail.
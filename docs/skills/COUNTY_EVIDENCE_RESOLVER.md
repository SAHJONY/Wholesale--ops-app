# SAHJONY County Evidence Resolver

## Purpose
Resolve wholesale verification gates using lawful, source-backed evidence without bypassing authentication, CAPTCHA, paywalls, rate limits, or access controls.

## Inputs
- deal_id
- property address
- parcel/APN
- legal description
- county/state
- known sale date(s)
- known auction date(s)

## Required outputs
For each gate return: `status`, `confidence`, `source_type`, `source_url_or_reference`, `observed_at`, `evidence_summary`, and `next_action`.

### 1. Current deed owner / seller authority
1. Search official county real-property index using parcel/APN, legal description, subdivision/lot/block, and known sale-date window.
2. Identify the deed/grantee instrument for the last arm's-length transfer.
3. Search forward from that instrument date through the current date for later deeds, deeds into/out of trusts/entities, corrective deeds, probate conveyances, divorce conveyances, or other title transfers.
4. Mark `current_deed_owner_verified=true` only when the indexed chain supports one current grantee and no later conveyance is found.
5. Mark `seller_authority_verified=true` only when the person/entity being contacted matches the verified owner or documented authorized signer.

### 2. Trustee / foreclosure instrument
1. Search official county real-property index for Notice of Trustee's Sale, Appointment/Substitution of Trustee, Deed of Trust, Assignment of Deed of Trust, and related instruments.
2. Correlate by parcel/legal description, grantor, and deed-of-trust recording references.
3. Record auction date, trustee, beneficiary/lender/servicer if stated, original principal if stated, and recording/file number.
4. Third-party auction indexes may corroborate but never replace the official instrument.

### 3. Liens / payoff
1. Build the recorded lien stack from deeds of trust, assignments, releases/satisfactions, tax liens, HOA liens, judgments, abstracts, mechanic's liens, and other indexed encumbrances.
2. A recorded original principal is not a payoff. Mark `payoff_verified=true` only from a current payoff/reinstatement statement supplied by the lienholder/servicer/title company or another authoritative source.
3. Do not infer lien release when no release instrument is found; mark status `open_or_unknown`.

### 4. Sold comps / ARV
1. Prefer verified closed sales, then MLS/public-record corroborated sold data.
2. Match property type, living area, bed/bath count, age, condition, location, lot, and sale recency.
3. Keep AVMs separate from closed-sale evidence.
4. Record low/base/high ARV and evidence confidence. Do not promote ARV to verified from an AVM alone.

### 5. Physical repair scope
1. Desktop-only inputs may establish a reserve, never a verified scope.
2. Require interior/exterior inspection, seller-provided current photos/video, licensed/qualified contractor scope, or equivalent source-backed condition evidence before setting `repairs_verified=true`.
3. Preserve unknown components explicitly: roof, HVAC, foundation, electrical, plumbing, water heater, windows, kitchen, baths, flooring, paint, exterior, permits, occupancy, debris/cleanout.

### 6. Outreach authorization
Outreach may become `authorized=true` only after:
- current owner/seller authority is verified;
- applicable DNC/TCPA/state solicitation checks pass for the chosen channel;
- no internal opt-out exists;
- the contact method is lawfully sourced and allowed by company policy.

Texas automated cold SMS/calling remains fail-closed until the compliance engine explicitly clears the channel.

## Access-control policy
Allowed:
- public web pages and public county search indexes;
- official APIs/data feeds authorized for SAHJONY;
- user-authenticated sessions supplied/authorized by the user;
- manual human retrieval when an official site requires login or purchase;
- title-company/attorney/servicer documents received lawfully.

Forbidden:
- CAPTCHA circumvention;
- authentication/session bypass;
- paywall bypass;
- rate-limit evasion;
- impersonation or credential stuffing;
- scraping disallowed/private records;
- fabricating owner, lien, payoff, or authority evidence.

## Deal #7 seed identifiers
- Address: 9438 Fairland Dr, Houston, TX 77051
- Parcel/APN: 0822670000025
- Legal: LT 25 BLK 10 BLUERIDGE SEC 1
- Known sale date: 2022-11-10
- Indexed auction date: 2026-09-01

### Current Deal #7 unresolved evidence targets
1. 2022 deed/grantee instrument and any later conveyance through 2026-08-18.
2. 2026 trustee-sale instrument and deed-of-trust chain.
3. Recorded lien stack plus current payoff/reinstatement statement.
4. Interior/exterior inspection or equivalent condition evidence.
5. Compliance clearance for the selected outreach channel.

## Completion rule
Never clear a gate because a likely value/name was found. Clear a gate only when evidence satisfies the source standard for that gate. Preserve `unknown` rather than guessing.

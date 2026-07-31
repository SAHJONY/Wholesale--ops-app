# SAHJONY Wholesale OS — Nationwide Acquisition Business

This document defines the operating model for converting the platform from an empty software shell into a real nationwide wholesale acquisition business.

## Truth standard

The platform is not considered populated merely because federal market-context data is available. A production lead must be backed by a reusable public-record or licensed provider source, normalized into the workspace, deduplicated, and retained with source provenance.

## Real acquisition sources

1. County assessor and recorder exports.
2. Tax delinquent, foreclosure, sheriff-sale, and lis pendens lists.
3. Code violations, vacant structures, demolition, nuisance, and permit records.
4. Probate and other legally reusable public court records.
5. PropStream exports where contractually permitted.
6. BatchData exports for enrichment where contractually permitted.
7. Licensed MLS/IDX exports for comps and listing intelligence.
8. USPS vacancy indicators only where legally licensed and available.

## Production intake

The existing `/data-intake/preview` and `/data-intake/commit` endpoints provide:

- 5,000 rows per batch.
- Required identity and property fields.
- Workspace isolation.
- Phone and address deduplication.
- Texas exclusion.
- Audit history.
- Dry-run preview before commit.

## Launch sequence

1. Load 25–50 verified records from one county.
2. Validate acceptance, duplicate, and rejection rates.
3. Confirm the CEO Command Center and acquisition pipeline reflect the new records.
4. Run human-reviewed qualification and underwriting.
5. Approve outreach only after DNC, consent, and exact-action approval checks.
6. Complete one supervised transaction.
7. Expand to 250–500 leads and a second provider.
8. Expand nationwide by county only after source terms, reliability, and economics are verified.

## KPIs

- Normalization success > 99%.
- Duplicate rate < 2% after source-specific cleanup.
- Provider success > 99%.
- Time from import to owner review < 1 business day.
- Every record has source and observation date.
- No unauthorized outbound action.
- Buyer-match precision > 80% after enough closed-deal history exists.

## Non-negotiable controls

- Texas remains excluded.
- MLS/IDX remains disabled until licensed.
- USPS vacancy remains disabled until legally available.
- Seller contact data must come from lawful and contractually permitted sources.
- No outreach, contract action, or buyer notification without a valid human approval for that exact action.

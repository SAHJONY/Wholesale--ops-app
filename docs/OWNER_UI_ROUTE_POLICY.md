# Owner UI route policy

SAHJONY Wholesale OS exposes only operator-facing pages that directly support the canonical wholesale workflow or required administration.

## Canonical operating surfaces

- `/owner` — Command Center
- `/owner/copilot` — OpenAI Wholesale Copilot
- `/owner/deal-factory` — nationwide source-backed opportunity analysis
- `/owner/attention` — approvals and blockers
- `/owner/acquisition` — prospects and acquisitions
- `/owner/real-deals` — verified deal workspace
- `/owner/buyer-intake` — buyer buy boxes and proof-of-funds workflow
- `/owner/properties` — property workspace
- `/owner/communications` — seller communications
- `/owner/sms-acquisition` — supervised campaign, scheduling, and attribution controls
- `/owner/disposition` — buyer disposition
- `/owner/closing` — title/closing execution
- `/owner/deal-intelligence` — comp-backed underwriting
- `/owner/lead-verification` — source verification
- `/owner/markets` — market selection
- `/owner/live-data` — data-source status
- `/owner/jobs` — AI workforce
- `/owner/integrations` — integrations
- `/owner/system-health` — system health
- `/owner/audit` — audit trail
- `/owner/security` — security administration

## Transitional pages retained but removed from primary navigation

The following routes remain until their unique functionality is migrated into a canonical surface:

- `/owner/deals` — still used for legacy deal deep links
- `/owner/public-data` — public data source discovery controls
- `/owner/provider-activation` — licensed-provider activation flow
- `/owner/sessions` — session administration

## Deletion rule

A standalone owner page may be deleted when all of the following are true:

1. Its user-facing capability is duplicated by a canonical operating surface or is internal-only.
2. No active frontend route depends on it.
3. Removing the page does not remove the underlying backend capability required by the OS.
4. Type-check, production build, and backend CI remain green.

Backend APIs, workers, and safety controls are not removed merely because an obsolete UI page is retired.

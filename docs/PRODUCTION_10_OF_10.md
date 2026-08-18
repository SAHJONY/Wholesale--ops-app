# SAHJONY Wholesale Ops — Production 10/10 Gate

A deployment is not considered fully operational because it merely builds or returns HTTP 200. Production readiness requires the complete revenue path to be verifiably available.

## Required golden path

1. Lead discovered or imported.
2. Property and owner evidence verified.
3. Contact eligibility evaluated before outreach.
4. Seller conversation captured and qualification updated.
5. Underwriting produces ARV, repair estimate, MAO, opening offer, and hard walkaway.
6. Human approval controls any material offer or contract action.
7. Executed deal is matched to evidence-backed buyers.
8. Buyer proof/capital evidence is explicit rather than inferred.
9. Disposition remains human-authorized before outreach or award.
10. Closing partner is selected from evidence-backed jurisdiction/strategy support.
11. Closing outcome feeds buyer/title intelligence.
12. Assignment revenue is attributed to the originating deal.

## Release gates

A production release is 10/10 only when all of the following are true:

- Frontend and backend deployment versions are in sync.
- Database is reachable and migrations are current.
- Authentication uses HttpOnly secure cookies and owner routes fail closed.
- Owner login does not expose an administrator identity in public markup.
- Authentication remains attemptable when a non-auth health probe is degraded.
- Integration Hub reports every required workflow as ready; setup/partial providers are explicitly visible.
- Reliability monitor has no unresolved critical provider alert.
- No critical operational module contains placeholder/stub content.
- Lead intake, underwriting, disposition, buyer matching, title matching, and closing routes are covered by regression tests.
- A synthetic golden deal completes end-to-end without bypassing approval gates.
- Production runtime has no unresolved P0/P1 application error.

## Provider truthfulness

Configured credentials are not equivalent to operational capability. A provider is production-ready only after an authenticated, non-destructive verification succeeds. Historical buyer behavior is not current proof of funds. Title-company capability is not legal authorization for a transaction structure. Public-record ownership/contact evidence remains provenance-scoped.

## Operating principle

AI prepares and prioritizes. Humans authorize material outreach, offers, contracts, buyer awards, and closing actions.

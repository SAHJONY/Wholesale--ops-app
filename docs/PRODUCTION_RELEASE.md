# Production Release Gate

SAHJONY Wholesale OS production release policy.

## Current release contract

- Application architecture: unified Vercel Services project (Next.js frontend + FastAPI backend).
- Production domain: `www.sahjony.com`.
- Database: Neon Postgres `wholesale-ops-db`.
- Required database migration head: `20260819_0013`.
- Seller outreach remains fail-closed unless authority and compliance gates pass.
- Buyer proof of funds is never inferred.
- JV compensation and marketing rights require written terms.

## 10/10 release gates

A production release is considered fully green only when all of the following are true:

1. Frontend and backend report the same Git commit through `/api/version`.
2. Vercel production deployment is READY and aliased to `www.sahjony.com`.
3. Neon `alembic_version` equals the repository migration head.
4. Required runtime tables exist, including buyer intelligence, voice, SMS, business OS, and title-company matching tables.
5. Public seller/buyer/partner/JV intake readiness is healthy.
6. Authenticated owner endpoints reject unauthenticated access.
7. Landing page, JV page, Owner OS, Market Intelligence, Buyer Network, Deal Room, Disposition, Closing, Phone OS, and SMS acquisition routes build successfully.
8. Production error/fatal logs show no unresolved release-blocking errors after smoke testing.
9. Assignment-fee and JV performance metrics distinguish projected pipeline economics from realized closed revenue.
10. No automated seller outreach is enabled merely by a public submission.

## JV revenue definitions

- Gross assignment fee = buyer/disposition price minus seller/contract price, floored at zero.
- Realized JV gross assignment revenue = gross assignment fees from closed JV deals.
- SAHJONY JV revenue = gross assignment fee multiplied by the documented SAHJONY split.
- Conversion rate = closed JV deals divided by total JV submissions.
- Days-to-buyer = elapsed calendar time from JV submission to the first documented buyer identification.

This file is an operational release manifest; it does not replace automated tests, database migrations, or production observability.

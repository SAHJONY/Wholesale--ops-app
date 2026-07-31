# Authentication Gateway Recovery Skill

## Objective

Detect and repair the failure mode where the backend health endpoint is online but browser authentication reports `Cannot connect to the backend` or Safari `Load failed`.

## Invariant

Browser authentication must never call the production backend origin directly. All login, health, password-reset, logout, and authenticated application requests must use same-origin frontend API gateways.

## Required routes

- `/login` — the only application sign-in page.
- `/api/owner-access/health` — public health proxy.
- `/api/owner-access/login` — public login proxy.
- `/api/backend/[...path]` — authenticated backend proxy.

## Legacy route policy

- `/owner` redirects to `/login?returnTo=/owner/deals`.
- `/owner-access` redirects to `/login?returnTo=/owner/deals`.
- Protected modules redirect to `/login?returnTo=<safe owner path>` when the session is missing or expired.

## Diagnostic procedure

1. Run the static contract check:

   ```bash
   python scripts/auth_gateway_check.py
   ```

2. Run the live gateway check:

   ```bash
   python scripts/auth_gateway_check.py \
     --base-url https://wholesale-ops-app-juan-gonzalezs-projects-94b6dfe9.vercel.app
   ```

3. Confirm the health gateway returns HTTP 200.
4. Confirm a deliberately invalid login returns an authentication error such as HTTP 401, not 404, 500, or 502.
5. Confirm `/owner` and `/owner-access` redirect to `/login`.
6. Sign in through `/login` with a valid authorized account.
7. Confirm the session opens `/owner/deals` and authenticated calls use `/api/backend/...`.

## Release blocker

Do not deploy when `scripts/auth_gateway_check.py` fails. A direct backend URL in a browser authentication component is a release-blocking defect.

## Security boundary

This skill does not bypass authentication or role enforcement. It bypasses only unreliable cross-origin browser transport by routing requests through the application's trusted same-origin server gateway.

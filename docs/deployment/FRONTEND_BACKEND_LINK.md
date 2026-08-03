# Frontend to Backend Link

## Public application

- Frontend: `https://wholesale-ops-app-juan-gonzalezs-projects-94b6dfe9.vercel.app`
- Backend target: `https://wholesale-ops-2kqe2x2q1-personal-d82253df.vercel.app`

## Runtime contract

Browser requests remain same-origin and use the frontend API gateways:

- `/api/owner-access/*` for login and health
- `/api/backend/*` for authenticated application traffic

The server-side gateway reads `BACKEND_URL`. Configure this variable in the frontend Vercel project for Preview and Production. Do not expose backend credentials or tokens through `NEXT_PUBLIC_*` variables.

## Required Vercel variable

```text
BACKEND_URL=https://wholesale-ops-2kqe2x2q1-personal-d82253df.vercel.app
```

After changing the variable, redeploy the frontend and run the authentication gateway check.

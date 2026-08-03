# Deploy the FastAPI backend on Vercel

Use a second Vercel project connected to the same GitHub repository.

> **The backend does not deploy itself. Confirm this before trusting a fix is live.**
>
> The frontend project has a GitHub integration and redeploys on every push to
> `main`. If the backend project is deployed from the CLI instead (`vercel
> --prod` from a laptop), the two drift apart every time someone merges without
> also running that command, and nothing announces it.
>
> This has already happened: the backend sat five merges behind `main` for ten
> days while the frontend stayed current. Production kept raising
> `TypeError: can't compare offset-naive and offset-aware datetimes` from a bug
> that had been fixed and merged weeks earlier — 47 errors across 14 users —
> because the fix had never been deployed.
>
> Check which commit production is actually running:
>
> ```bash
> curl -s https://YOUR-BACKEND-PROJECT.vercel.app/health | jq .deployed
> ```
>
> `deployed.commit` is the real answer. A `null` commit means the instance was
> not built by Vercel; a commit that is not the tip of `main` means the backend
> is stale no matter how green CI looks. `version` is a hardcoded string and
> proves nothing.
>
> To remove the failure mode rather than watch for it, connect the backend
> project to the repository in Vercel (Settings → Git) with production branch
> `main` and root directory `backend`, so it deploys on merge like the frontend.

## Project settings

- Repository: `SAHJONY/Wholesale--ops-app`
- Production branch: `main`
- Root Directory: `backend`
- Framework Preset: `Other`
- Build Command: leave empty
- Output Directory: leave empty
- Install Command: leave empty

Vercel will use `backend/vercel.json`, `backend/api/index.py`, and `backend/requirements.txt`.

## Required environment variables

Set these for Production, Preview, and Development:

```env
DATABASE_URL=postgresql+psycopg://...
APP_URL=https://YOUR-FRONTEND-VERCEL-DOMAIN
BLAND_WEBHOOK_SECRET=CREATE_A_LONG_RANDOM_SECRET
```

Optional integrations:

```env
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
BLAND_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_MAPS_API_KEY=
HUBSPOT_ACCESS_TOKEN=
```

## Database requirement

Do not use SQLite in production on Vercel. Serverless local storage is ephemeral. Attach a managed PostgreSQL database and place its connection string in `DATABASE_URL`.

## Verification

After deployment, test the exact generated Vercel domain:

```bash
curl "https://YOUR-BACKEND-PROJECT.vercel.app/health"
curl "https://YOUR-BACKEND-PROJECT.vercel.app/leads"
```

Expected health response:

```json
{"status":"ok","service":"wholesale-ops-api"}
```

## Connect the frontend

In the existing frontend Vercel project, add:

```env
NEXT_PUBLIC_API_URL=https://YOUR-BACKEND-PROJECT.vercel.app
```

Redeploy the frontend after saving the variable.

## Bland.ai webhook

Set Bland.ai's webhook URL to:

```text
https://YOUR-BACKEND-PROJECT.vercel.app/webhooks/bland
```

If `BLAND_WEBHOOK_SECRET` is set, send the same value in the `X-Webhook-Secret` header.

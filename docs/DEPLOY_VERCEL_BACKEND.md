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
> To remove the failure mode rather than watch for it, either connect the
> backend project to the repository in Vercel (Settings → Git) with production
> branch `main` and root directory `backend`, or use the deploy workflow below,
> which drives both projects from the repository.

## Deploying from the repository

`.github/workflows/deploy.yml` deploys on every push to `main`, in the order the
system actually requires: migrate, then backend, then frontend. Relying on the
Vercel Git integration alone proved unreliable here — it produced a production
deployment for only two of six consecutive merges — and the backend was never
connected to it at all.

Add one secret under **Settings → Secrets and variables → Actions**:

| Secret | Required | Purpose |
| --- | --- | --- |
| `VERCEL_TOKEN` | yes | A Vercel access token with deploy rights. Without it every job skips with a warning instead of failing. |
| `PRODUCTION_DATABASE_URL` | no | When set, `alembic upgrade head` runs before the backend deploys, so new code never meets an older schema. When unset, migrations are skipped and any new tables are reported missing rather than created. |

The Vercel org and project IDs live in the workflow in plain text. They are
identifiers rather than credentials and are useless without the token; keeping
them there means setup is one secret instead of five.

After the backend deploys, the workflow asks the running service which commit it
reports and compares it to the commit being deployed. Reporting no commit fails
the run, because that can only mean code older than revision reporting is still
being served. Reporting a *different* commit warns rather than fails, since a CLI
deploy does not always record git metadata the way a Git-integration build does,
and a check that fails on ambiguity gets switched off.

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

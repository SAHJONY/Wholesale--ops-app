# Deploy the FastAPI backend on Vercel

Use a second Vercel project connected to the same GitHub repository.

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

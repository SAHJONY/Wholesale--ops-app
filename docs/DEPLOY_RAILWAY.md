# Deploy the FastAPI backend to Railway

## 1. Create the Railway project

1. Sign in to Railway.
2. Create a new project from GitHub.
3. Select `SAHJONY/Wholesale--ops-app`.
4. Set the service root directory to `backend` if Railway does not detect the repository-level `railway.json` correctly.
5. Add a PostgreSQL service to the same Railway project.

## 2. Required environment variables

Set these on the backend service:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
APP_URL=https://YOUR-VERCEL-PRODUCTION-DOMAIN.vercel.app
BLAND_WEBHOOK_SECRET=GENERATE_A_LONG_RANDOM_SECRET
```

Optional integrations:

```env
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
QSTASH_TOKEN=
BLAND_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_MAPS_API_KEY=
HUBSPOT_ACCESS_TOKEN=
```

Do not commit real credentials to GitHub.

## 3. Build and start settings

Dockerfile path:

```text
backend/Dockerfile
```

Start command used by the container:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Health endpoint:

```text
/health
```

## 4. Generate a public domain

After the service deploys:

1. Open the backend service.
2. Open **Settings → Networking**.
3. Generate a public Railway domain.
4. Copy the full HTTPS URL.

## 5. Verify the backend

Replace the placeholder with the real Railway domain:

```bash
curl https://YOUR-RAILWAY-DOMAIN/health
curl https://YOUR-RAILWAY-DOMAIN/leads
```

Expected health result:

```json
{"status":"ok","service":"wholesale-ops-api"}
```

## 6. Connect Vercel

In the Vercel project, add this environment variable for Production, Preview, and Development:

```env
NEXT_PUBLIC_API_URL=https://YOUR-RAILWAY-DOMAIN
```

Redeploy Vercel after saving the variable.

## 7. Production smoke test

```bash
curl -X POST https://YOUR-RAILWAY-DOMAIN/underwrite \
  -H "Content-Type: application/json" \
  -d '{
    "arv": 250000,
    "repairs": 50000,
    "assignment_fee": 15000,
    "mao_factor": 0.70
  }'
```

Expected MAO:

```json
{"arv":250000.0,"repairs":50000.0,"assignment_fee":15000.0,"mao":110000.0}
```

## Acceptance criteria

- Railway deployment is green.
- `/health` returns HTTP 200.
- PostgreSQL is connected through `DATABASE_URL`.
- Vercel has the real `NEXT_PUBLIC_API_URL`.
- The public dashboard shows live backend counts rather than fallback zeros.

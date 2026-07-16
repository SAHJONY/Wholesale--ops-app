# SAHJONY Workspace Authentication and CRM

This release adds an additive organization and CRM layer without removing the existing wholesale operations endpoints.

## Capabilities

- Organization bootstrap
- Owner API credential shown once
- API-key authentication through `X-API-Key` or `Authorization: Bearer`
- Team membership and roles
- Tenant-scoped leads and deals
- CRM stage changes and activity history
- Follow-up tasks
- Owner workspace at `/owner`

## Roles

- `owner`
- `admin`
- `manager`
- `acquisitions`
- `disposition`
- `transaction_coordinator`
- `va`
- `viewer`

## Recommended environment variable

Set a strong server-only value in the backend Vercel project:

```env
BOOTSTRAP_SECRET=<long-random-secret>
```

After the first organization exists, bootstrap is locked unless the request supplies the matching `X-Bootstrap-Secret` header.

## Deploy

Backend:

```bash
cd ~/Wholesale--ops-app
git checkout main
git pull origin main
cd backend
vercel --prod --scope personal-d82253df
```

Frontend:

```bash
cd ~/Wholesale--ops-app
vercel --prod
```

Confirm the frontend project has:

```env
NEXT_PUBLIC_API_URL=https://backend-pi-opal-65.vercel.app
```

## Owner setup

Open the frontend route:

```text
/owner
```

Create the organization using the setup form. The returned API key is displayed only once. Store it in a password manager.

The browser console stores the connected owner key in local storage for this MVP. A later release should replace browser API keys with short-lived sessions and httpOnly cookies before onboarding third-party customers.

## Import existing production records

After the owner workspace is connected, click **Import existing**. This creates tenant links for current leads and deals without duplicating the underlying records.

## API examples

```bash
curl https://backend-pi-opal-65.vercel.app/auth/me \
  -H "X-API-Key: $SAHJONY_API_KEY"

curl https://backend-pi-opal-65.vercel.app/crm/pipeline \
  -H "X-API-Key: $SAHJONY_API_KEY"
```

## Security boundary

The new `/auth/*` and `/crm/*` endpoints are authenticated and tenant-scoped. The original legacy endpoints remain available for compatibility with the current dashboard. Before opening the platform to multiple external companies, migrate all legacy mutation endpoints behind the workspace principal and enforce organization ownership on autonomy, campaign, approval, and deal actions.

# Tenant-Scoped Autonomous Operations

This release adds authenticated organization boundaries around the operational control plane.

## Protected routes

All routes below require `Authorization: Bearer <owner-or-team-api-key>` or `X-API-Key`.

- `GET /workspace/dashboard`
- `GET|POST /workspace/buyers`
- `GET /workspace/deals`
- `GET /workspace/properties/{property_id}/buyer-appetite`
- `POST /workspace/deals/{deal_id}/seller-offer`
- `POST /workspace/deals/{deal_id}/closing`
- `GET /workspace/autonomy/status`
- `POST /workspace/autonomy/run`
- `POST /workspace/autonomy/tasks`
- `POST /workspace/autonomy/execute`
- `POST /workspace/approvals/{approval_id}/decision`

## Role policy

- viewer: read-only workspace access
- va: basic CRM access
- acquisitions: create/update leads
- disposition: create buyers
- transaction_coordinator: initialize closing workflows
- manager: run agents, queue tasks, prepare offers
- admin: manage team and credentials
- owner: all actions and approval decisions

## Isolation model

Legacy operational tables remain unchanged. `workspace_entities` links each organization to its leads, deals, buyers, tasks, approvals, campaigns, offers, and agent runs. Protected routes only query linked records.

This additive model avoids a destructive live migration while enforcing tenant boundaries for the new application surface.

## Deployment

```bash
cd ~/Wholesale--ops-app
git checkout main
git pull origin main
cd backend
vercel --prod --scope personal-d82253df
```

The frontend project should redeploy automatically from GitHub.

## Verification

Unauthenticated requests must return HTTP 401:

```bash
curl -i https://wholesale-ops-app-juan-gonzalezs-projects-94b6dfe9.vercel.app/api/backend/workspace/dashboard
```

Authenticated request:

```bash
curl -s https://wholesale-ops-app-juan-gonzalezs-projects-94b6dfe9.vercel.app/api/backend/workspace/dashboard \
  -H "Authorization: Bearer $SAHJONY_OWNER_KEY" | python3 -m json.tool
```

Do not store the owner key in GitHub or paste it into chat. Use a password manager or a local shell secret.

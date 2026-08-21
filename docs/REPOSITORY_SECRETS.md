# SAHJONY Wholesale — GitHub Actions Secrets Contract

Never commit secret values to the repository. Configure them in **GitHub → Settings → Secrets and variables → Actions → Repository secrets**.

## Runtime / infrastructure
- `DATABASE_URL`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `QSTASH_TOKEN`
- `QSTASH_CURRENT_SIGNING_KEY`
- `QSTASH_NEXT_SIGNING_KEY`

## Bland.AI
- `BLAND_AI_API_KEY`
- `BLAND_AI_WEBHOOK_SECRET`

## AI providers
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`

## Property / address / market data
- `SMARTY_AUTH_ID`
- `SMARTY_AUTH_TOKEN`
- `ATTOM_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `CENSUS_API_KEY`
- `BATCHDATA_API_TOKEN`
- `BATCHDATA_API_KEY`
- `BATCHDATA_SANDBOX_API_KEY`
- `AUTONOMOUS_PROPERTY_FEED_TOKEN`

## CRM / email
- `HUBSPOT_ACCESS_TOKEN`
- `RESEND_API_KEY`
- `RESEND_WEBHOOK_SECRET`

## Notes
- `BLAND_INBOUND_ORGANIZATION_ID`, phone numbers, agent IDs, URLs, model names, feature flags, and email addresses are configuration values, not credentials. Keep them in environment variables/variables rather than GitHub Secrets unless there is a specific operational reason to hide them.
- GitHub Actions secrets do **not** automatically become Vercel Environment Variables. Production runtime credentials must also exist in the relevant Vercel project(s), or be synchronized by an explicit deployment workflow.
- Store raw provider keys only. Do not wrap them in quotes and do not prepend `Bearer ` unless the provider explicitly requires it.

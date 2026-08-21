# Bland API key rotation

`BLAND_AI_API_KEY` is a Vercel runtime secret. Rotating or replacing the key does not change an already-built deployment.

After every Bland API key rotation:

1. Update `BLAND_AI_API_KEY` in the Vercel project(s) that execute the FastAPI backend.
2. Redeploy production so the new runtime receives the updated secret.
3. Run the safe Bland diagnostic and require `GET https://api.bland.ai/v1/me` to return HTTP 200 before any live call test.
4. Validate organization membership, caller-ID/inbound-number inventory, and webhook configuration only after authentication passes.
5. Keep recording disabled and SMS disabled under the current operating policy.

Never commit the API key itself to Git history, logs, documentation, or issue comments.

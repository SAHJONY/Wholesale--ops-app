import { NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';

/**
 * Confirms that the frontend and backend are running the same repository commit.
 *
 * In the target Vercel Services architecture both services deploy atomically from
 * the same GitHub commit. BACKEND_INTERNAL_URL is injected by the frontend ->
 * backend service binding. BACKEND_URL is retained only for local or explicit
 * non-Vercel deployments.
 */
export async function GET() {
  const frontend = process.env.VERCEL_GIT_COMMIT_SHA || process.env.GIT_COMMIT_SHA || null;

  let backend: string | null = null;
  let reachable = false;
  let detail: string | null = null;

  try {
    const response = await fetch(`${BACKEND_URL}/health`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
    });
    reachable = response.ok;
    const text = await response.text();
    if (!response.ok) {
      detail = `Backend /health returned ${response.status}`;
    } else {
      try {
        backend = JSON.parse(text)?.deployed?.commit ?? null;
        if (backend === null) {
          detail = 'Backend did not report a commit, so release synchronization cannot be proven.';
        }
      } catch {
        detail = `Backend /health was not JSON: ${text.slice(0, 120)}`;
      }
    }
  } catch (error) {
    detail = `Backend unreachable: ${error instanceof Error ? error.message : 'request failed'}`;
  }

  const status =
    !reachable ? 'backend_unreachable'
    : frontend && backend ? (frontend === backend ? 'in_sync' : 'drifted')
    : 'unknown';

  return NextResponse.json(
    {
      status,
      frontend_commit: frontend,
      backend_commit: backend,
      backend_transport: process.env.BACKEND_INTERNAL_URL ? 'vercel_service_binding' : 'explicit_backend_url',
      detail,
      note:
        'Target architecture: frontend and FastAPI backend deploy atomically as Vercel Services from SAHJONY/Wholesale--ops-app.',
    },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}

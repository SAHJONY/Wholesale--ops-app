import { NextResponse } from 'next/server';

// Falls back to the production host so deployed behaviour is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

/**
 * Whether the frontend and backend were built from the same commit.
 *
 * The two deploy as separate Vercel projects from one repository. The frontend
 * has a GitHub integration and ships on every merge; the backend has shipped by
 * hand. Nothing compared them, so the backend sat five merges behind for ten
 * days while production raised a crash that had already been fixed and merged.
 *
 * Both projects build from the same repository, so their commits agreeing is
 * the whole check -- no GitHub API call and no token. A mismatch does not say
 * which side is behind, only that they disagree, which is the part that was
 * invisible.
 */
export async function GET() {
  // VERCEL_GIT_COMMIT_SHA is set only by Git-integration builds. Both projects
  // deploy from the workflow by CLI, which stamps GIT_COMMIT_SHA instead, so
  // without the fallback this side of the comparison is always unknown.
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
          // Silence means the running code never received the deploy-time
          // stamp: either it predates revision reporting, or it was shipped
          // outside the workflow. Both mean it is not the commit just deployed.
          detail = 'Backend did not report a commit, so it is running code that was not stamped by the deploy workflow.';
        }
      } catch {
        detail = `Backend /health was not JSON: ${text.slice(0, 120)}`;
      }
    }
  } catch (error) {
    detail = `Backend unreachable: ${error instanceof Error ? error.message : 'request failed'}`;
  }

  // Only a confident mismatch is called drift. Unknown on either side is
  // reported as unknown rather than guessed at.
  const status =
    !reachable ? 'backend_unreachable'
    : frontend && backend ? (frontend === backend ? 'in_sync' : 'drifted')
    : 'unknown';

  return NextResponse.json(
    {
      status,
      frontend_commit: frontend,
      backend_commit: backend,
      detail,
      note:
        'Frontend and backend deploy as separate Vercel projects from one repository. '
        + 'Differing commits mean one of them did not ship.',
    },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}

import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND = process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const joined = path.join('/');
  if (joined !== 'snapshot') return NextResponse.json({ detail: 'Unsupported security route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  try {
    const response = await fetch(`${BACKEND}/security/${joined}`, { headers: { Authorization: authorization }, cache: 'no-store', signal: AbortSignal.timeout(20000) });
    const text = await response.text();
    if (response.status === 404) return NextResponse.json({ status: 'setup', controls: {}, runtime: { active_blocks: 0, tracked_buckets: 0, rate_limited: 0 }, detail: 'Security API is not deployed yet.' });
    return new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' } });
  } catch (error) {
    return NextResponse.json({ status: 'setup', controls: {}, runtime: { active_blocks: 0, tracked_buckets: 0, rate_limited: 0 }, detail: `Security backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` });
  }
}

export const GET = proxy;

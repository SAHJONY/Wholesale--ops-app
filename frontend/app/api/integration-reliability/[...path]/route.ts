import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot' || joined === 'run-now';
}

function fallback(path: string[]) {
  const joined = path.join('/');
  if (joined === 'snapshot') {
    return NextResponse.json({
      summary: { open: 0, critical: 0, resolved: 0 },
      alerts: [],
      runs: [],
      degraded_mode: true,
      detail: 'Reliability backend is not deployed yet; provider readiness remains available.',
    });
  }
  if (joined === 'run-now') {
    return NextResponse.json({
      run_id: 0,
      status: 'degraded',
      alerts_opened: 0,
      alerts_resolved: 0,
      degraded_mode: true,
      detail: 'Reliability checks are unavailable until the backend route is deployed.',
    });
  }
  return NextResponse.json({ detail: 'Unsupported integration reliability route' }, { status: 404 });
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported integration reliability route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND_URL}/integration-reliability/${path.join('/')}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    if (response.status === 404) return fallback(path);
    const text = await response.text();
    return new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' } });
  } catch (error) {
    if (path.join('/') === 'snapshot') return fallback(path);
    return NextResponse.json({ detail: `Integration reliability backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

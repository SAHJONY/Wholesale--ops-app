import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot' || joined === '' || joined === 'run-next' || /^\d+\/retry$/.test(joined);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const joined = path.join('/');
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported jobs route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const suffix = joined ? `/${joined}` : '';
    const response = await fetch(`${BACKEND_URL}/jobs${suffix}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    if (response.status === 404 && joined === 'snapshot') {
      return NextResponse.json({ generated_at: new Date().toISOString(), counts: {}, supported_job_types: [], jobs: [], status: 'setup' });
    }
    const text = await response.text();
    return new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' } });
  } catch (error) {
    return NextResponse.json({ detail: `Jobs backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'catalog' || joined === 'readiness' || joined === 'normalize-preview';
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const joined = path.join('/');
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported public data route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND_URL}/public-data/${joined}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    if (response.status === 404 && joined === 'catalog') {
      return NextResponse.json({ organization_id: 0, providers: [], enabled_count: 0, licensed_disabled_count: 0, safety: { dry_run_default: true, outbound_actions: false, texas_excluded: true, human_approval_required: true } });
    }
    const text = await response.text();
    return new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' } });
  } catch (error) {
    return NextResponse.json({ detail: `Public data backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

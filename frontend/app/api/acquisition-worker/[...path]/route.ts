import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot'
    || joined === 'run-pending'
    || /^leads\/\d+\/run$/.test(joined);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported acquisition-worker route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND_URL}/acquisition-worker/${path.join('/')}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(60000),
    });
    const text = await response.text();
    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    return NextResponse.json({
      detail: `Acquisition worker backend unavailable: ${error instanceof Error ? error.message : 'request failed'}`,
    }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

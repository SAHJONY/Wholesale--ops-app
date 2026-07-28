import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot'
    || /^(property|seller|buyer)\/\d+$/.test(joined)
    || /^(property|seller|buyer)\/\d+\/(facts|rebuild)$/.test(joined);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported intelligence route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const target = `${BACKEND_URL}/intelligence-platform/${path.join('/')}`;
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(target, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Backend request failed';
    return NextResponse.json({ detail: `Intelligence backend unavailable: ${message}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

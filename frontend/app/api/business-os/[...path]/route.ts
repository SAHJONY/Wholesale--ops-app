import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behaviour is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';
const ALLOWED = new Set(['snapshot', 'plan', 'transactions', 'obligations', 'playbooks/defaults']);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const joined = path.join('/');
  const dynamicAllowed = /^transactions\/\d+$/.test(joined) || /^obligations\/\d+$/.test(joined);
  if (!ALLOWED.has(joined) && !dynamicAllowed) return NextResponse.json({ detail: 'Unsupported business route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  try {
    const response = await fetch(`${BACKEND_URL}/business-os/${joined}${request.nextUrl.search}`, {
      method: request.method,
      headers: { 'Content-Type': 'application/json', Authorization: authorization },
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text(),
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    return new NextResponse(await response.arrayBuffer(), {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    return NextResponse.json({ detail: `Business OS backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

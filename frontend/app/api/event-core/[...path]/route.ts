import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = 'https://backend-pi-opal-65.vercel.app';
const ALLOWED_PATHS = new Set([
  'snapshot',
  'process',
  'emit',
]);

function allowed(path: string[]) {
  const joined = path.join('/');
  return ALLOWED_PATHS.has(joined)
    || /^events\/\d+\/replay$/.test(joined)
    || /^subscriptions\/\d+$/.test(joined);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported event-core route' }, { status: 404 });

  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }

  const target = `${BACKEND_URL}/event-core/${path.join('/')}`;
  const headers: Record<string, string> = {
    Authorization: authorization,
    'Content-Type': 'application/json',
  };

  let body: string | undefined;
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    body = await request.text();
  }

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });
    const text = await response.text();
    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Backend request failed';
    return NextResponse.json({ detail: `Event backend unavailable: ${message}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;

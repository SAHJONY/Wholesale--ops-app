import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND = process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';
const ALLOWED = new Set(['criteria', 'rank']);

async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  // Prefixes cover the parameterised routes (market/{zip}).
  const permitted = ALLOWED.has(route) || route.startsWith('market/');
  if (!permitted) {
    return NextResponse.json({ detail: 'Unsupported market-selection route' }, { status: 404 });
  }

  const auth = request.headers.get('authorization');
  if (!auth?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }

  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();

  try {
    const response = await fetch(`${BACKEND}/market-selection/${route}${request.nextUrl.search}`, {
      method: request.method,
      headers: { Authorization: auth, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    const text = await response.text();
    if (response.status === 404) {
      return NextResponse.json(
        { detail: 'market-selection API is not deployed on the backend yet. Redeploy the backend from latest main, then retry.' },
        { status: 503 },
      );
    }
    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: `market-selection backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` },
      { status: 502 },
    );
  }
}

export const GET = handler;
export const POST = handler;

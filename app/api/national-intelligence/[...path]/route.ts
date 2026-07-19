import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot'
    || joined === 'refresh'
    || /^properties\/\d+$/.test(joined);
}

function setupPayload(detail: string) {
  return {
    status: 'setup',
    detail,
    summary: {
      properties: 0,
      high_priority: 0,
      ownership_verified: 0,
      projected_assignment_fees: 0,
      average_opportunity_score: 0,
    },
    properties: [],
    markets: [],
    runs: [],
  };
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported national intelligence route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND_URL}/national-intelligence/${path.join('/')}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    const text = await response.text();
    if (response.status >= 500 && path.join('/') === 'snapshot') {
      return NextResponse.json(setupPayload('National Intelligence backend is not ready. Redeploy the latest backend and verify database connectivity.'), { status: 200 });
    }
    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    if (path.join('/') === 'snapshot') {
      return NextResponse.json(setupPayload(`National Intelligence backend unavailable: ${error instanceof Error ? error.message : 'request failed'}`), { status: 200 });
    }
    return NextResponse.json({
      detail: `National intelligence backend unavailable: ${error instanceof Error ? error.message : 'request failed'}`,
    }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

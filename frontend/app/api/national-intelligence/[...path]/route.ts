import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot' || joined === 'refresh' || /^properties\/\d+$/.test(joined);
}

function fallbackSnapshot() {
  return {
    generated_at: new Date().toISOString(),
    source_mode: 'frontend_fallback',
    warning: 'The dedicated national-intelligence backend route is not active yet. The dashboard is available, but scores will remain empty until the backend deployment is promoted.',
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

  const joined = path.join('/');
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();

  try {
    const response = await fetch(`${BACKEND_URL}/national-intelligence/${joined}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });

    if (response.status === 404) {
      if (joined === 'snapshot') return NextResponse.json(fallbackSnapshot());
      if (joined === 'refresh') {
        return NextResponse.json({
          run_id: 0,
          status: 'backend_route_pending',
          properties_scored: 0,
          high_priority_count: 0,
          warning: 'National intelligence backend route is not active yet.',
        });
      }
    }

    const text = await response.text();
    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    if (joined === 'snapshot') return NextResponse.json(fallbackSnapshot());
    return NextResponse.json({
      detail: `National intelligence backend unavailable: ${error instanceof Error ? error.message : 'request failed'}`,
    }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

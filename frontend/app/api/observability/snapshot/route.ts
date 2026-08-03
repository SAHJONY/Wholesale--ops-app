import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

export async function GET(request: NextRequest) {
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }
  try {
    const response = await fetch(`${BACKEND_URL}/observability/snapshot`, {
      headers: { Authorization: authorization },
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });
    if (response.status === 404) {
      return NextResponse.json({
        setup_mode: true,
        instance: { deployment: 'not deployed', environment: 'unknown', uptime_seconds: 0, serverless_notice: 'Deploy the latest backend to activate observability.' },
        database: { status: 'unknown', latency_ms: null },
        requests: { sample_size: 0, error_count: 0, slow_count: 0, average_duration_ms: 0, slow_threshold_ms: 1500, status_counts: {}, top_routes: [] },
        recent_errors: [], recent_slow_requests: [],
      });
    }
    const text = await response.text();
    return new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' } });
  } catch (error) {
    return NextResponse.json({ detail: `Observability backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

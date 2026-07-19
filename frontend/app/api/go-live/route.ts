import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = 'https://backend-pi-opal-65.vercel.app';

export async function GET(request: NextRequest) {
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }

  try {
    const response = await fetch(`${BACKEND_URL}/go-live/snapshot`, {
      headers: { Authorization: authorization },
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });

    if (response.status === 404) {
      return NextResponse.json({
        status: 'setup', score: 0, blocker_count: 1, checks: [], missing_routes: ['/go-live/snapshot'],
        providers: {}, workspace: { leads: 0, properties: 0, buyers: 0, deals: 0 }, jobs: {}, owner_pages: [],
        launch_policy: { automatic_production_launch: false, owner_approval_required: true, message: 'Deploy the latest backend to activate go-live checks.' }
      });
    }

    const text = await response.text();
    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    return NextResponse.json({ detail: `Go-live backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

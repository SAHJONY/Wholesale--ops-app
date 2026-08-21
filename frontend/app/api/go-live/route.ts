import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';
const SESSION_COOKIE = 'sahjony_owner_session';

export async function GET(request: NextRequest) {
  const explicit = request.headers.get('authorization');
  const cookieToken = request.cookies.get(SESSION_COOKIE)?.value || '';
  const authorization = explicit?.toLowerCase().startsWith('bearer ')
    ? explicit
    : cookieToken
      ? `Bearer ${cookieToken}`
      : '';
  if (!authorization) {
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
    const outgoing = new NextResponse(text || null, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
      },
    });
    if (response.status === 401 || response.status === 403) {
      outgoing.cookies.set(SESSION_COOKIE, '', { httpOnly: true, secure: true, sameSite: 'strict', path: '/', maxAge: 0 });
    }
    return outgoing;
  } catch (error) {
    return NextResponse.json({ detail: `Go-live backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';
const SESSION_COOKIE = 'sahjony_owner_session';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot' || joined === 'run';
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported validation route' }, { status: 404 });
  const explicit = request.headers.get('authorization');
  const cookieToken = request.cookies.get(SESSION_COOKIE)?.value || '';
  const authorization = explicit?.toLowerCase().startsWith('bearer ')
    ? explicit
    : cookieToken
      ? `Bearer ${cookieToken}`
      : '';
  if (!authorization) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND_URL}/launch-validation/${path.join('/')}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(45000),
    });
    if (response.status === 404 && path.join('/') === 'snapshot') {
      return NextResponse.json({ latest_report: null, latest_run_at: null, status: 'setup' });
    }
    const text = await response.text();
    const outgoing = new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store' } });
    if (response.status === 401 || response.status === 403) outgoing.cookies.set(SESSION_COOKIE, '', { httpOnly: true, secure: true, sameSite: 'strict', path: '/', maxAge: 0 });
    return outgoing;
  } catch (error) {
    return NextResponse.json({ detail: `Validation backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

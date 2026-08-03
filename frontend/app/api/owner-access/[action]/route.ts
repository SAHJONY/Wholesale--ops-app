import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';
const SESSION_COOKIE = 'sahjony_owner_session';
const SESSION_MAX_AGE = 60 * 60 * 8;

const ACTIONS: Record<string, { path: string; method: 'GET' | 'POST' }> = {
  health: { path: '/health', method: 'GET' },
  login: { path: '/human-auth/login', method: 'POST' },
  logout: { path: '/human-auth/logout', method: 'POST' },
  'request-password-reset': { path: '/human-auth/request-password-reset', method: 'POST' },
  'reset-password': { path: '/human-auth/reset-password', method: 'POST' },
};

function clearSession(response: NextResponse) {
  response.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    secure: true,
    sameSite: 'strict',
    path: '/',
    maxAge: 0,
  });
  return response;
}

async function proxy(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;

  if (action === 'session') {
    const token = request.cookies.get(SESSION_COOKIE)?.value || '';
    if (!token) {
      return NextResponse.json(
        { authenticated: false },
        { headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
      );
    }
    try {
      const upstream = await fetch(`${BACKEND_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      });
      if (upstream.status === 401 || upstream.status === 403) {
        return clearSession(NextResponse.json(
          { authenticated: false },
          { status: 401, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
        ));
      }
      if (!upstream.ok) {
        return NextResponse.json(
          { authenticated: false, detail: 'Session validation unavailable' },
          { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
        );
      }
      const principal = await upstream.json();
      return NextResponse.json(
        { authenticated: true, principal },
        { headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
      );
    } catch {
      return NextResponse.json(
        { authenticated: false, detail: 'Session validation unavailable' },
        { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
      );
    }
  }

  const mapping = ACTIONS[action];
  if (!mapping) {
    return NextResponse.json({ detail: 'Unsupported owner access action' }, { status: 404 });
  }

  let body = mapping.method === 'POST' ? await request.text() : undefined;
  if (action === 'logout') {
    const token = request.cookies.get(SESSION_COOKIE)?.value || '';
    body = JSON.stringify({ token });
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}${mapping.path}`, {
      method: mapping.method,
      headers: mapping.method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });

    const text = await upstream.text();
    const response = new NextResponse(text || null, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
        'X-Robots-Tag': 'noindex',
      },
    });

    if (action === 'login' && upstream.ok) {
      try {
        const payload = text ? JSON.parse(text) : {};
        const token = String(payload.access_token || '');
        if (!token) return NextResponse.json({ detail: 'Sign-in succeeded without a session token' }, { status: 502 });
        response.cookies.set(SESSION_COOKIE, token, {
          httpOnly: true,
          secure: true,
          sameSite: 'strict',
          path: '/',
          maxAge: SESSION_MAX_AGE,
        });
      } catch {
        return NextResponse.json({ detail: 'Unreadable sign-in response' }, { status: 502 });
      }
    }

    if (action === 'logout') return clearSession(response);
    return response;
  } catch (error) {
    const response = NextResponse.json(
      { detail: `Backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` },
      { status: 502 },
    );
    return action === 'logout' ? clearSession(response) : response;
  }
}

export const GET = proxy;
export const POST = proxy;

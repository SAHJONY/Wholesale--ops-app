import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE = 'sahjony_owner_session';

function safeOwnerReturnTo(value: string | null, fallback = '/owner') {
  if (!value) return fallback;
  if (value === '/owner') return value;
  return value.startsWith('/owner/') && !value.startsWith('//') ? value : fallback;
}

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  if (pathname === '/') {
    const url = request.nextUrl.clone();
    url.pathname = '/owner';
    return NextResponse.redirect(url);
  }

  if (pathname.startsWith('/api/') && !pathname.startsWith('/api/owner-access/')) {
    const session = request.cookies.get(SESSION_COOKIE)?.value;
    if (session) {
      const headers = new Headers(request.headers);
      headers.set('authorization', `Bearer ${session}`);
      return NextResponse.next({ request: { headers } });
    }
  }

  if (pathname === '/owner-access') {
    const url = request.nextUrl.clone();
    const requestedReturnTo = request.nextUrl.searchParams.get('returnTo');
    url.pathname = '/login';
    url.search = '';
    url.searchParams.set('returnTo', safeOwnerReturnTo(requestedReturnTo));
    return NextResponse.redirect(url);
  }

  if (pathname === '/login') {
    return NextResponse.next();
  }

  if (pathname === '/owner' || pathname.startsWith('/owner/')) {
    if (!request.cookies.get(SESSION_COOKIE)?.value) {
      const url = request.nextUrl.clone();
      url.pathname = '/login';
      url.search = '';
      url.searchParams.set('returnTo', safeOwnerReturnTo(pathname));
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/', '/api/:path*', '/owner-access', '/login', '/owner/:path*'],
};

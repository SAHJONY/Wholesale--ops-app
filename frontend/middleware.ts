import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE = 'sahjony_owner_session';

function safeOwnerReturnTo(value: string | null, fallback = '/owner') {
  if (!value) return fallback;
  if (value === '/owner') return value;
  return value.startsWith('/owner/') && !value.startsWith('//') ? value : fallback;
}

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  if (pathname === '/owner-access') {
    const url = request.nextUrl.clone();
    const requestedReturnTo = request.nextUrl.searchParams.get('returnTo');
    url.pathname = '/login';
    url.search = '';
    url.searchParams.set('returnTo', safeOwnerReturnTo(requestedReturnTo));
    return NextResponse.redirect(url);
  }

  if (pathname === '/login') {
    if (request.cookies.get(SESSION_COOKIE)?.value) {
      const url = request.nextUrl.clone();
      url.pathname = safeOwnerReturnTo(request.nextUrl.searchParams.get('returnTo'));
      url.search = '';
      return NextResponse.redirect(url);
    }
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
  matcher: ['/owner-access', '/login', '/owner/:path*'],
};

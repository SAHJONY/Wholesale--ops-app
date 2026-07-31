import { NextRequest, NextResponse } from 'next/server';

function safeOwnerReturnTo(value: string | null, fallback = '/owner/deals') {
  if (!value) return fallback;
  return value.startsWith('/owner/') && !value.startsWith('//') ? value : fallback;
}

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  if (pathname === '/owner' || pathname === '/owner-access') {
    const url = request.nextUrl.clone();
    const requestedReturnTo = request.nextUrl.searchParams.get('returnTo');
    url.pathname = '/login';
    url.search = '';
    url.searchParams.set('returnTo', safeOwnerReturnTo(requestedReturnTo));
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/owner', '/owner-access'],
};

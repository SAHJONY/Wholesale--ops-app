import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname === '/owner-access') {
    const url = request.nextUrl.clone();
    const returnTo = request.nextUrl.searchParams.get('returnTo') || '/owner/deals';
    url.pathname = '/login';
    url.search = '';
    url.searchParams.set('returnTo', returnTo.startsWith('/owner') && !returnTo.startsWith('//') ? returnTo : '/owner');
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/owner-access'],
};

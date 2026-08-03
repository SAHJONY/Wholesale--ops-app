import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot' || joined === 'export.csv';
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported audit route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const query = request.nextUrl.search;
  try {
    const response = await fetch(`${BACKEND_URL}/audit/${path.join('/')}${query}`, {
      method: 'GET',
      headers: { Authorization: authorization },
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    if (response.status === 404 && path.join('/') === 'snapshot') {
      return NextResponse.json({
        generated_at: new Date().toISOString(), window_days: 30, total: 0,
        category_counts: {}, activity_type_counts: {}, items: [], status: 'setup',
        retention_note: 'Deploy the audit backend to activate governance reporting.'
      });
    }
    const body = await response.arrayBuffer();
    const headers = new Headers();
    headers.set('Content-Type', response.headers.get('content-type') || 'application/json');
    const disposition = response.headers.get('content-disposition');
    if (disposition) headers.set('Content-Disposition', disposition);
    return new NextResponse(body, { status: response.status, headers });
  } catch (error) {
    return NextResponse.json({ detail: `Audit backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;

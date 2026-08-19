import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'queue-property-candidates'
    || /^leads\/\d+\/packet$/.test(joined)
    || /^leads\/\d+\/owner-record-evidence$/.test(joined)
    || /^leads\/\d+\/evidence$/.test(joined)
    || /^leads\/\d+\/apply-contact-ready$/.test(joined);
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) {
    return NextResponse.json({ detail: 'Unsupported owner resolution route' }, { status: 404 });
  }

  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }

  const body = request.method === 'GET' || request.method === 'HEAD'
    ? undefined
    : await request.text();

  try {
    const response = await fetch(`${BACKEND_URL}/owner-resolution/${path.join('/')}`, {
      method: request.method,
      headers: {
        Authorization: authorization,
        'Content-Type': 'application/json',
      },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(45000),
    });

    const text = await response.text();
    return new NextResponse(text || null, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
      },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: `Owner resolution backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;

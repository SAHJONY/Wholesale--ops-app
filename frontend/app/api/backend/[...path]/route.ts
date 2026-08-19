import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (!ALLOWED_METHODS.has(request.method)) {
    return NextResponse.json({ detail: 'Method not allowed' }, { status: 405 });
  }

  const { path } = await context.params;
  const backendPath = `/${path.map(segment => encodeURIComponent(segment)).join('/')}`;
  const query = request.nextUrl.search;
  const authorization = request.headers.get('authorization');
  const contentType = request.headers.get('content-type');
  const body = request.method === 'GET' ? undefined : await request.text();

  const headers: Record<string, string> = {};
  if (authorization) headers.Authorization = authorization;
  if (contentType) headers['Content-Type'] = contentType;

  try {
    const response = await fetch(`${BACKEND_URL}${backendPath}${query}`, {
      method: request.method,
      headers,
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });

    const responseBody = await response.text();
    return new NextResponse(responseBody || null, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
        'X-Robots-Tag': 'noindex',
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail: `Backend unavailable: ${error instanceof Error ? error.message : 'request failed'}`,
      },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

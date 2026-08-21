import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND = process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';

async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!['snapshot', 'run'].includes(route)) {
    return NextResponse.json({ detail: 'Unsupported route' }, { status: 404 });
  }
  const auth = request.headers.get('authorization');
  if (!auth) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const body = request.method === 'GET' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND}/test-deal/${route}${request.nextUrl.search}`, {
      method: request.method,
      headers: { Authorization: auth, 'Content-Type': 'application/json' },
      body,
      cache: 'no-store',
    });
    const text = await response.text();
    if (response.status === 404) {
      return NextResponse.json({ status: 'setup', detail: 'Test Deal API is not deployed yet.' }, { status: 200 });
    }
    return new NextResponse(text, { status: response.status, headers: { 'Content-Type': 'application/json' } });
  } catch {
    return NextResponse.json({ status: 'setup', detail: 'Test Deal API is unavailable.' }, { status: 200 });
  }
}

export const GET = handler;
export const POST = handler;

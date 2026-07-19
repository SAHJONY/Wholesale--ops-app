import { NextRequest, NextResponse } from 'next/server';

const BACKEND = 'https://backend-pi-opal-65.vercel.app';

async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!['snapshot', 'preview', 'commit'].includes(route)) {
    return NextResponse.json({ detail: 'Unsupported route' }, { status: 404 });
  }
  const auth = request.headers.get('authorization');
  if (!auth) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const body = request.method === 'GET' ? undefined : await request.text();
  const response = await fetch(`${BACKEND}/data-intake/${route}`, {
    method: request.method,
    headers: { Authorization: auth, 'Content-Type': 'application/json' },
    body,
    cache: 'no-store',
  });
  const text = await response.text();
  return new NextResponse(text, { status: response.status, headers: { 'Content-Type': 'application/json' } });
}

export const GET = handler;
export const POST = handler;

import { NextRequest, NextResponse } from 'next/server';

const BACKEND = 'https://backend-pi-opal-65.vercel.app';

// Exact routes plus the two parameterised shapes the console calls. Anything
// else is rejected here rather than proxied blindly to the backend.
const EXACT = ['status', 'briefing', 'forecast', 'underwrite', 'leads/ranked', 'disposition/plan'];
const CALL_BRIEF = /^leads\/\d+\/call-brief$/;

function allowed(route: string) {
  return EXACT.includes(route) || CALL_BRIEF.test(route);
}

const OFFLINE = {
  detail: 'Decision Intelligence API is unavailable. Deploy the latest backend to activate it.',
  offline: true,
};

async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!allowed(route)) {
    return NextResponse.json({ detail: 'Unsupported route' }, { status: 404 });
  }
  const auth = request.headers.get('authorization');
  if (!auth) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });

  const body = request.method === 'GET' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND}/deal-intelligence/${route}`, {
      method: request.method,
      headers: { Authorization: auth, 'Content-Type': 'application/json' },
      body,
      cache: 'no-store',
    });
    if (response.status === 404) return NextResponse.json(OFFLINE, { status: 200 });
    const text = await response.text();
    return new NextResponse(text, {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return NextResponse.json(OFFLINE, { status: 200 });
  }
}

export const GET = handler;
export const POST = handler;

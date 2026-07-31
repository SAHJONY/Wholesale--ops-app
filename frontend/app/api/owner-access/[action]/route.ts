import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://wholesale-ops-2kqe2x2q1-personal-d82253df.vercel.app';
const ALLOWED_ACTIONS = new Set(['health', 'login']);

async function proxy(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;
  if (!ALLOWED_ACTIONS.has(action)) {
    return NextResponse.json({ detail: 'Unsupported owner access action' }, { status: 404 });
  }

  const backendPath = action === 'health' ? '/health' : '/human-auth/login';
  const method = action === 'health' ? 'GET' : 'POST';
  const body = method === 'POST' ? await request.text() : undefined;

  try {
    const response = await fetch(`${BACKEND_URL}${backendPath}`, {
      method,
      headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
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
      {
        detail: `Backend unavailable: ${error instanceof Error ? error.message : 'request failed'}`,
      },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://wholesale-ops-2kqe2x2q1-personal-d82253df.vercel.app';
const ACTIONS: Record<string, { path: string; method: 'GET' | 'POST' }> = {
  health: { path: '/health', method: 'GET' },
  login: { path: '/human-auth/login', method: 'POST' },
  'request-password-reset': { path: '/human-auth/request-password-reset', method: 'POST' },
  'reset-password': { path: '/human-auth/reset-password', method: 'POST' },
};

async function proxy(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;
  const mapping = ACTIONS[action];
  if (!mapping) {
    return NextResponse.json({ detail: 'Unsupported owner access action' }, { status: 404 });
  }

  const body = mapping.method === 'POST' ? await request.text() : undefined;

  try {
    const response = await fetch(`${BACKEND_URL}${mapping.path}`, {
      method: mapping.method,
      headers: mapping.method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
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
        'X-Robots-Tag': 'noindex',
      },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: `Backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;

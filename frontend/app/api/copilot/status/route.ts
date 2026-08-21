import { NextRequest, NextResponse } from 'next/server';

async function requireSession(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie.includes('sahjony_owner_session=')) return { ok: false as const, status: 401 };
  try {
    const response = await fetch(new URL('/api/owner-access/session', request.url), {
      cache: 'no-store',
      headers: { cookie },
      signal: AbortSignal.timeout(10_000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.authenticated) return { ok: false as const, status: response.status === 503 ? 503 : 401 };
    return { ok: true as const, status: 200 };
  } catch {
    return { ok: false as const, status: 503 };
  }
}

export async function GET(request: NextRequest) {
  const session = await requireSession(request);
  if (!session.ok) {
    return NextResponse.json(
      { detail: session.status === 503 ? 'Owner session validation unavailable' : 'Owner session required' },
      { status: session.status, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
    );
  }

  return NextResponse.json({
    configured: Boolean(process.env.OPENAI_API_KEY),
    model: process.env.OPENAI_MODEL || 'gpt-5.6-sol',
    responses_api: true,
    tools: {
      web_search: true,
      file_search: Boolean(process.env.OPENAI_VECTOR_STORE_ID),
      workspace_functions: [
        'list_wholesale_skills',
        'list_deal_factory_candidates',
        'analyze_workspace_property',
        'list_verified_buyers',
      ],
      computer_use: false,
      realtime_voice: false,
    },
    runtime: 'nextjs_same_origin',
    note: 'OpenAI credentials are read from the same Vercel project that serves the Wholesale OS frontend.',
  }, {
    headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' },
  });
}

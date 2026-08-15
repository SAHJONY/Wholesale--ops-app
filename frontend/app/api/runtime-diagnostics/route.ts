import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

async function requireOwnerAdmin(request: NextRequest) {
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
    const role = String(data?.principal?.role || '').toLowerCase();
    if (!['owner', 'admin'].includes(role)) return { ok: false as const, status: 403 };
    return { ok: true as const, status: 200 };
  } catch {
    return { ok: false as const, status: 503 };
  }
}

export async function GET(request: NextRequest) {
  const session = await requireOwnerAdmin(request);
  if (!session.ok) {
    const detail = session.status === 503 ? 'Owner session validation unavailable' : session.status === 403 ? 'Owner or admin role required' : 'Owner session required';
    return NextResponse.json({ detail }, { status: session.status, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } });
  }

  const target = new URL(BACKEND_URL);
  const result: Record<string, unknown> = {
    frontend_environment: process.env.VERCEL_ENV || 'unknown',
    backend_host: target.host,
    backend_url_source: process.env.BACKEND_URL ? 'BACKEND_URL' : 'legacy_fallback',
    frontend_openai_key_present: Boolean(process.env.OPENAI_API_KEY),
    frontend_vector_store_present: Boolean(process.env.OPENAI_VECTOR_STORE_ID),
  };

  try {
    const cookie = request.headers.get('cookie') || '';
    const authorization = request.headers.get('authorization') || '';
    const response = await fetch(`${BACKEND_URL}/openai-copilot/status`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
      headers: { cookie, ...(authorization ? { authorization } : {}) },
    });
    const text = await response.text();
    let body: unknown = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = null; }

    result.backend_http_status = response.status;
    if (body && typeof body === 'object') {
      const data = body as Record<string, unknown>;
      result.backend_openai_configured = Boolean(data.configured);
      const tools = data.tools && typeof data.tools === 'object' ? data.tools as Record<string, unknown> : {};
      result.backend_file_search_enabled = Boolean(tools.file_search);
      result.backend_model = typeof data.model === 'string' ? data.model : null;
    }
  } catch (error) {
    result.backend_http_status = null;
    result.backend_error = error instanceof Error ? error.message : 'backend request failed';
  }

  return NextResponse.json(result, {
    headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' },
  });
}

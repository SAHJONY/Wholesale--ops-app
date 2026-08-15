import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

export async function GET() {
  const target = new URL(BACKEND_URL);
  const result: Record<string, unknown> = {
    frontend_environment: process.env.VERCEL_ENV || 'unknown',
    backend_host: target.host,
    backend_url_source: process.env.BACKEND_URL ? 'BACKEND_URL' : 'legacy_fallback',
    frontend_openai_key_present: Boolean(process.env.OPENAI_API_KEY),
    frontend_vector_store_present: Boolean(process.env.OPENAI_VECTOR_STORE_ID),
  };

  try {
    const response = await fetch(`${BACKEND_URL}/openai-copilot/status`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
      headers: { Authorization: 'Bearer cookie-session' },
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
    headers: {
      'Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex',
    },
  });
}

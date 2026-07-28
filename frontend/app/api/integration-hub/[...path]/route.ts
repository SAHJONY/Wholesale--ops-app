import { NextRequest, NextResponse } from 'next/server';

// Falls back to the production host so deployed behavior is unchanged, but
// lets the app be pointed at a local or staging backend without editing source.
const BACKEND_URL = process.env.BACKEND_URL || 'https://backend-pi-opal-65.vercel.app';

function allowed(path: string[]) {
  const joined = path.join('/');
  return joined === 'snapshot' || joined === 'check' || /^providers\/[a-z0-9_-]+$/.test(joined);
}

async function backendJson(path: string, authorization: string) {
  const response = await fetch(`${BACKEND_URL}${path}`, {
    headers: { Authorization: authorization, 'Content-Type': 'application/json' },
    cache: 'no-store',
    signal: AbortSignal.timeout(30000),
  });
  const text = await response.text();
  let body: any = {};
  if (text) {
    try { body = JSON.parse(text); } catch { body = { detail: text }; }
  }
  return { response, body };
}

async function legacySnapshot(authorization: string) {
  const [catalogResult, readinessResult] = await Promise.all([
    backendJson('/integrations/catalog', authorization),
    backendJson('/integrations/readiness', authorization),
  ]);
  if (!catalogResult.response.ok) {
    return NextResponse.json(catalogResult.body, { status: catalogResult.response.status });
  }
  if (!readinessResult.response.ok) {
    return NextResponse.json(readinessResult.body, { status: readinessResult.response.status });
  }
  const providers = (catalogResult.body.providers || []).map((provider: any) => ({
    ...provider,
    configured_variables: provider.configured_variables || [],
    missing_variables: provider.missing_variables || [],
    last_check: null,
  }));
  const readiness = readinessResult.body || {};
  const workflow_readiness = {
    lead_acquisition: Boolean(readiness.ready_for_live_acquisition),
    property_verification: providers.some((p: any) => p.id === 'county_records'),
    seller_outreach: Boolean(readiness.ready_for_outbound),
    email_delivery: providers.some((p: any) => ['gmail','outlook'].includes(p.id) && ['configured','available_public_or_manual'].includes(p.state)),
    crm_sync: providers.some((p: any) => p.id === 'hubspot' && p.state === 'configured'),
    scheduling: providers.some((p: any) => p.id === 'google_calendar' && p.state === 'configured'),
    contract_execution: Boolean(readiness.ready_for_contracts),
    accounting: providers.some((p: any) => p.id === 'quickbooks' && p.state === 'configured'),
    payments: providers.some((p: any) => p.id === 'stripe' && p.state === 'configured'),
  };
  return NextResponse.json({
    generated_at: new Date().toISOString(),
    summary: {
      providers: providers.length,
      configured: providers.filter((p: any) => ['configured','available_public_or_manual'].includes(p.state)).length,
      partial: providers.filter((p: any) => p.state === 'partial').length,
      not_configured: providers.filter((p: any) => p.state === 'not_configured').length,
    },
    workflow_readiness,
    providers,
    runs: [],
    fallback_mode: true,
  });
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!allowed(path)) return NextResponse.json({ detail: 'Unsupported integration hub route' }, { status: 404 });
  const authorization = request.headers.get('authorization');
  if (!authorization?.toLowerCase().startsWith('bearer ')) return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  const joined = path.join('/');
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();
  try {
    const response = await fetch(`${BACKEND_URL}/integration-hub/${joined}`, {
      method: request.method,
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });
    if (response.status === 404 && joined === 'snapshot') return legacySnapshot(authorization);
    if (response.status === 404 && joined === 'check') {
      return NextResponse.json({ run_id: 0, status: 'fallback', providers_checked: 0, providers_ready: 0, providers_blocked: 0, results: [] });
    }
    const text = await response.text();
    return new NextResponse(text || null, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' } });
  } catch (error) {
    if (joined === 'snapshot') return legacySnapshot(authorization);
    return NextResponse.json({ detail: `Integration backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;

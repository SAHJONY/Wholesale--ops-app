import { NextRequest, NextResponse } from 'next/server';

const ROLE_RANK: Record<string, number> = {
  viewer: 10,
  va: 20,
  acquisitions: 30,
  disposition: 30,
  transaction_coordinator: 30,
  manager: 70,
  admin: 90,
  owner: 100,
};

async function requireOwnerSession(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie.includes('sahjony_owner_session=')) return { ok: false as const, status: 401, principal: null };
  try {
    const response = await fetch(new URL('/api/owner-access/session', request.url), {
      cache: 'no-store',
      headers: { cookie },
      signal: AbortSignal.timeout(10_000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.authenticated) {
      return { ok: false as const, status: response.status === 503 ? 503 : 401, principal: null };
    }
    const role = String(data?.principal?.role || '').toLowerCase();
    if ((ROLE_RANK[role] || 0) < ROLE_RANK.manager) return { ok: false as const, status: 403, principal: data?.principal || null };
    return { ok: true as const, status: 200, principal: data?.principal || null };
  } catch {
    return { ok: false as const, status: 503, principal: null };
  }
}

export async function GET(request: NextRequest) {
  const auth = await requireOwnerSession(request);
  if (!auth.ok) {
    return NextResponse.json(
      { detail: auth.status === 503 ? 'Owner session validation unavailable' : auth.status === 403 ? 'Manager or higher required' : 'Owner session required' },
      { status: auth.status, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
    );
  }

  const provider = String(process.env.VOICE_TELEPHONY_PROVIDER || 'bland').trim().toLowerCase();
  const inbound = String(process.env.VOICE_INBOUND_NUMBER || '').trim() || null;
  const transferTarget = String(process.env.VOICE_HUMAN_TRANSFER_TARGET || '').trim() || null;
  const webhookReady = Boolean(process.env.OPENAI_WEBHOOK_SECRET);
  const routingConflict = Boolean(inbound && transferTarget && inbound === transferTarget);

  return NextResponse.json({
    runtime: 'openai_realtime_voice_os',
    openai: {
      configured: Boolean(process.env.OPENAI_API_KEY),
      model: process.env.OPENAI_REALTIME_MODEL || 'gpt-realtime',
      voice: process.env.OPENAI_REALTIME_VOICE || 'marin',
      webhook_secret_configured: webhookReady,
    },
    telephony: {
      provider,
      provider_configured: Boolean(provider),
      inbound_number_configured: Boolean(inbound),
      inbound_number: inbound,
      human_transfer_target_configured: Boolean(transferTarget),
      sip_domain_configured: Boolean(process.env.VOICE_SIP_DOMAIN),
      routing_conflict: routingConflict,
    },
    controls: {
      inbound_accept: Boolean(process.env.OPENAI_API_KEY && webhookReady && inbound && !routingConflict),
      transfer: Boolean(process.env.OPENAI_API_KEY && transferTarget && !routingConflict),
      hangup: Boolean(process.env.OPENAI_API_KEY),
      verified_inbound_webhook_ingress: webhookReady,
      inbound_auto_accept: false,
      outbound_autodial: false,
      outbound_requires_compliance: true,
      outbound_requires_owner_approval: true,
    },
    note: routingConflict
      ? 'VOICE_INBOUND_NUMBER and VOICE_HUMAN_TRANSFER_TARGET must be different; call transfer is blocked to prevent a routing loop.'
      : 'Webhook ingress is signature-verified when OPENAI_WEBHOOK_SECRET is configured. Auto-accept and outbound autodial remain fail-closed until SIP routing and persistent call-event audit are proven end-to-end.',
  }, {
    headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' },
  });
}

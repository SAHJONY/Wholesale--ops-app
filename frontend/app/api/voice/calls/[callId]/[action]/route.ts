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

async function requireManager(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie.includes('sahjony_owner_session=')) return { ok: false as const, status: 401, principal: null };
  try {
    const response = await fetch(new URL('/api/owner-access/session', request.url), {
      cache: 'no-store', headers: { cookie }, signal: AbortSignal.timeout(10_000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.authenticated) return { ok: false as const, status: response.status === 503 ? 503 : 401, principal: null };
    const role = String(data?.principal?.role || '').toLowerCase();
    if ((ROLE_RANK[role] || 0) < ROLE_RANK.manager) return { ok: false as const, status: 403, principal: data?.principal || null };
    return { ok: true as const, status: 200, principal: data?.principal || null };
  } catch {
    return { ok: false as const, status: 503, principal: null };
  }
}

async function audit(request: NextRequest, payload: Record<string, unknown>) {
  const cookie = request.headers.get('cookie') || '';
  const authorization = request.headers.get('authorization') || '';
  const response = await fetch(new URL('/api/backend/crm/activities', request.url), {
    method: 'POST', cache: 'no-store', signal: AbortSignal.timeout(10_000),
    headers: { 'Content-Type': 'application/json', cookie, ...(authorization ? { authorization } : {}) },
    body: JSON.stringify(payload),
  });
  return response.ok;
}

function safeCallId(value: string) {
  return /^rtc_[A-Za-z0-9_-]{8,200}$/.test(value);
}

function normalizeE164(raw: string) {
  const value = raw.trim();
  return /^\+[1-9]\d{7,14}$/.test(value) ? value : null;
}

function phoneTarget(raw: string) {
  const value = normalizeE164(raw);
  return value ? `tel:${value}` : null;
}

export async function POST(request: NextRequest, context: { params: Promise<{ callId: string; action: string }> }) {
  const auth = await requireManager(request);
  if (!auth.ok) return NextResponse.json({ detail: auth.status === 403 ? 'Manager or higher required' : 'Owner session required' }, { status: auth.status });

  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return NextResponse.json({ detail: 'OPENAI_API_KEY is not configured' }, { status: 503 });

  const { callId, action } = await context.params;
  if (!safeCallId(callId)) return NextResponse.json({ detail: 'Invalid Realtime call id' }, { status: 422 });
  if (!['accept', 'refer', 'hangup', 'reject'].includes(action)) return NextResponse.json({ detail: 'Unsupported call action' }, { status: 404 });

  let body: Record<string, unknown> | undefined;
  if (action === 'accept') {
    body = {
      type: 'realtime',
      model: process.env.OPENAI_REALTIME_MODEL || 'gpt-realtime',
      instructions: process.env.OPENAI_VOICE_INSTRUCTIONS || 'You are the SAHJONY Wholesale Voice Agent. Clearly disclose that you are an AI assistant. Be concise and professional. Gather seller motivation, timeline, property condition, and price. Never promise an offer, clear title, legal result, financing approval, or contract. Escalate requests for binding commitments to a human.',
      audio: {
        output: { voice: process.env.OPENAI_REALTIME_VOICE || 'marin' },
        input: { turn_detection: { type: 'server_vad', silence_duration_ms: 650, prefix_padding_ms: 300 } },
      },
    };
  } else if (action === 'refer') {
    const configured = String(process.env.VOICE_HUMAN_TRANSFER_TARGET || '').trim();
    const requested = String((await request.json().catch(() => ({})))?.target || '').trim();
    const target = normalizeE164(requested || configured);
    const inbound = normalizeE164(String(process.env.VOICE_INBOUND_NUMBER || '').trim());
    if (!target) return NextResponse.json({ detail: 'A valid E.164 human transfer target is required' }, { status: 422 });
    if (inbound && target === inbound) {
      return NextResponse.json({ detail: 'Human transfer target cannot equal the AI inbound number; transfer loop blocked' }, { status: 422 });
    }
    body = { target_uri: phoneTarget(target) };
  } else if (action === 'reject') {
    const payload = await request.json().catch(() => ({}));
    const statusCode = Number(payload?.status_code || 603);
    if (![486, 603].includes(statusCode)) return NextResponse.json({ detail: 'Only SIP 486 or 603 are permitted by this control plane' }, { status: 422 });
    body = { status_code: statusCode };
  }

  const auditStarted = await audit(request, {
    activity_type: 'openai_realtime_call_action_requested',
    summary: `Realtime call ${action} requested`,
    metadata: { call_id: callId, action, runtime: 'nextjs_same_origin_voice' },
  }).catch(() => false);
  if (!auditStarted) return NextResponse.json({ detail: 'Audit service unavailable; call action was not sent' }, { status: 503 });

  const response = await fetch(`https://api.openai.com/v1/realtime/calls/${encodeURIComponent(callId)}/${action}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(20_000),
  });
  const text = await response.text();
  const result = text ? (() => { try { return JSON.parse(text); } catch { return { raw: text.slice(0, 500) }; } })() : {};

  await audit(request, {
    activity_type: response.ok ? 'openai_realtime_call_action_completed' : 'openai_realtime_call_action_failed',
    summary: `Realtime call ${action} ${response.ok ? 'completed' : 'failed'}`,
    metadata: { call_id: callId, action, http_status: response.status, runtime: 'nextjs_same_origin_voice' },
  }).catch(() => false);

  if (!response.ok) return NextResponse.json({ detail: result?.error?.message || `OpenAI call action failed (${response.status})` }, { status: response.status });
  return NextResponse.json({ ok: true, call_id: callId, action, provider: 'openai_realtime', result }, { headers: { 'Cache-Control': 'no-store' } });
}

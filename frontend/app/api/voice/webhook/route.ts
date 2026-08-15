import OpenAI from 'openai';

export const runtime = 'nodejs';

function safeCallId(value: unknown): value is string {
  return typeof value === 'string' && /^rtc_[A-Za-z0-9_-]{8,200}$/.test(value);
}

export async function POST(request: Request) {
  const webhookSecret = String(process.env.OPENAI_WEBHOOK_SECRET || '').trim();
  if (!webhookSecret) {
    return Response.json(
      { detail: 'OPENAI_WEBHOOK_SECRET is not configured' },
      { status: 503, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
    );
  }

  const body = await request.text();
  const client = new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
    webhookSecret,
  });

  let event: any;
  try {
    event = client.webhooks.unwrap(body, request.headers);
  } catch {
    return new Response('Invalid signature', {
      status: 400,
      headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' },
    });
  }

  if (event?.type !== 'realtime.call.incoming') {
    return Response.json(
      { ok: true, handled: false, event_type: event?.type || 'unknown' },
      { headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
    );
  }

  const callId = event?.data?.call_id;
  if (!safeCallId(callId)) {
    return Response.json(
      { detail: 'Verified webhook contained an invalid Realtime call id' },
      { status: 422, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
    );
  }

  // The webhook boundary is now cryptographically verified. Production auto-accept
  // stays fail-closed until the verified inbound event can be persisted to the CRM
  // without relying on a browser/owner session. The authenticated call-control route
  // can already accept/reject/refer/hang up this call id safely.
  return Response.json(
    {
      ok: true,
      handled: true,
      event_type: event.type,
      call_id: callId,
      verified: true,
      auto_accept: false,
      next_action: 'persist_verified_inbound_event_then_accept',
    },
    { headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
  );
}

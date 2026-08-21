import OpenAI from 'openai';
import { send } from '@vercel/queue';

import { acceptAgenticSipCall, type VoiceRuntimeContext } from '../../../../lib/agenticVoiceRuntime';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const TOPIC = 'sahjony-realtime-calls';

function required(name: 'OPENAI_API_KEY' | 'OPENAI_WEBHOOK_SECRET'): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function voiceOrganizationId(): number {
  const raw = (process.env.OPENAI_VOICE_ORGANIZATION_ID || process.env.BLAND_INBOUND_ORGANIZATION_ID || '').trim();
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) throw new Error('OPENAI_VOICE_ORGANIZATION_ID is not configured');
  return value;
}

function sipHeader(headers: Array<{ name?: string; value?: string }> | undefined, name: string): string | null {
  const match = headers?.find((item) => String(item.name || '').toLowerCase() === name.toLowerCase());
  return match?.value ? String(match.value) : null;
}

function extractPhone(value: string | null): string | null {
  if (!value) return null;
  const match = value.match(/\+\d{10,15}/);
  return match?.[0] || null;
}

export async function POST(request: Request) {
  const body = await request.text();
  const openai = new OpenAI({ apiKey: required('OPENAI_API_KEY'), webhookSecret: required('OPENAI_WEBHOOK_SECRET') });

  let event: any;
  try {
    event = openai.webhooks.unwrap(body, request.headers);
  } catch (error) {
    console.error('Rejected OpenAI voice webhook signature', error);
    return Response.json({ accepted: false, error: 'invalid_signature' }, { status: 400 });
  }

  if (event.type !== 'realtime.call.incoming') {
    return Response.json({ accepted: true, ignored: true, type: event.type });
  }

  const callId = String(event.data?.call_id || '').trim();
  if (!callId) return Response.json({ accepted: false, error: 'missing_call_id' }, { status: 422 });

  const headers = Array.isArray(event.data?.sip_headers) ? event.data.sip_headers : [];
  const callerPhone = extractPhone(sipHeader(headers, 'from') || sipHeader(headers, 'p-asserted-identity'));
  const inboundNumber = extractPhone(sipHeader(headers, 'to')) || process.env.VOICE_INBOUND_NUMBER || '+12164804413';
  const context: VoiceRuntimeContext = {
    callId,
    organizationId: voiceOrganizationId(),
    callerPhone,
    inboundNumber,
  };

  // Queue first with a short delay so a durable worker is guaranteed to exist
  // before the model starts requesting local tools. Idempotency absorbs webhook retries.
  const queued = await send(TOPIC, context, {
    idempotencyKey: callId,
    retentionSeconds: 3600,
    delaySeconds: 1,
  });

  try {
    await acceptAgenticSipCall(context);
  } catch (error) {
    console.error('OpenAI Realtime call acceptance failed', { callId, error });
    return Response.json({ accepted: false, queued: queued.messageId, error: 'call_accept_failed' }, { status: 502 });
  }

  return Response.json({ accepted: true, call_id: callId, queue_message_id: queued.messageId });
}

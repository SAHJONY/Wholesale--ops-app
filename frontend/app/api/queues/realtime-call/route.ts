import { handleCallback, send } from '@vercel/queue';

import { runAgenticSipSession, type VoiceRuntimeContext } from '../../../../lib/agenticVoiceRuntime';

export const runtime = 'nodejs';
export const maxDuration = 300;

const TOPIC = 'sahjony-realtime-calls';
const SLICE_RUNTIME_MS = 230 * 1000;
const MAX_SLICES = 30;

type VoiceSliceMessage = VoiceRuntimeContext & {
  slice?: number;
};

function validMessage(value: unknown): value is VoiceSliceMessage {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<VoiceSliceMessage>;
  const slice = item.slice ?? 0;
  return (
    typeof item.callId === 'string' &&
    item.callId.length >= 8 &&
    Number.isInteger(item.organizationId) &&
    Number(item.organizationId) > 0 &&
    Number.isInteger(slice) &&
    slice >= 0 &&
    slice < MAX_SLICES
  );
}

const queueCallback = handleCallback(
  async (message, metadata) => {
    if (!validMessage(message)) {
      throw new Error('Invalid SAHJONY Realtime call queue message');
    }

    const slice = message.slice ?? 0;
    console.log('Starting durable SAHJONY SIP session slice', {
      callId: message.callId,
      slice,
      messageId: metadata.messageId,
      deliveryCount: metadata.deliveryCount,
    });

    const result = await runAgenticSipSession(message, SLICE_RUNTIME_MS, slice === 0);
    console.log('SAHJONY SIP session slice completed', {
      callId: message.callId,
      slice,
      reason: result.reason,
    });

    if (result.reason === 'timeout' && slice + 1 < MAX_SLICES) {
      const nextSlice = slice + 1;
      await send(
        TOPIC,
        { ...message, slice: nextSlice },
        {
          idempotencyKey: `${message.callId}:slice:${nextSlice}`,
          retentionSeconds: 3600,
          delaySeconds: 1,
        },
      );
      console.log('Queued next SAHJONY SIP session slice', {
        callId: message.callId,
        nextSlice,
      });
    }
  },
  {
    visibilityTimeoutSeconds: 300,
    retry: (_error, metadata) => {
      if (metadata.deliveryCount >= 5) return { acknowledge: true };
      return { afterSeconds: Math.min(120, 2 ** metadata.deliveryCount * 5) };
    },
  },
);

// @vercel/queue's callback accepts an object containing the Request. Next.js 14
// requires route exports themselves to accept Request/NextRequest directly, so
// adapt the signature here while preserving Vercel's callback implementation.
export async function POST(request: Request): Promise<Response> {
  return queueCallback({ request });
}

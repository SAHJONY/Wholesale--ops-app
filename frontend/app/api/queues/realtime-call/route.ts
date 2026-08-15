import { handleCallback } from '@vercel/queue';

import { runAgenticSipSession, type VoiceRuntimeContext } from '../../../../lib/agenticVoiceRuntime';

export const runtime = 'nodejs';
export const maxDuration = 1800;

function validMessage(value: unknown): value is VoiceRuntimeContext {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<VoiceRuntimeContext>;
  return typeof item.callId === 'string' && item.callId.length >= 8 && Number.isInteger(item.organizationId) && Number(item.organizationId) > 0;
}

export const POST = handleCallback(
  async (message, metadata) => {
    if (!validMessage(message)) {
      throw new Error('Invalid SAHJONY Realtime call queue message');
    }
    console.log('Starting durable SAHJONY SIP session', {
      callId: message.callId,
      messageId: metadata.messageId,
      deliveryCount: metadata.deliveryCount,
    });
    const result = await runAgenticSipSession(message, 25 * 60 * 1000);
    console.log('SAHJONY SIP session worker completed', { callId: message.callId, reason: result.reason });
  },
  {
    visibilityTimeoutSeconds: 1800,
    retry: (_error, metadata) => {
      if (metadata.deliveryCount >= 5) return { acknowledge: true };
      return { afterSeconds: Math.min(120, 2 ** metadata.deliveryCount * 5) };
    },
  },
);

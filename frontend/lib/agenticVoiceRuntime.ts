import { createHmac } from 'node:crypto';

import OpenAI from 'openai';
import {
  OpenAIRealtimeSIP,
  RealtimeAgent,
  RealtimeSession,
  tool,
} from '@openai/agents/realtime';
import { z } from 'zod';

const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';
const MODEL = process.env.OPENAI_REALTIME_MODEL || 'gpt-realtime';
const VOICE = process.env.OPENAI_REALTIME_VOICE || 'marin';
const TRANSFER_TARGET = process.env.VOICE_HUMAN_TRANSFER_TARGET || '+12816628581';
const DOMAIN = 'sahjony-agentic-voice-service-v1';

export type VoiceRuntimeContext = {
  callId: string;
  organizationId: number;
  callerPhone?: string | null;
  inboundNumber?: string | null;
};

function requireEnv(name: 'OPENAI_API_KEY' | 'OPENAI_WEBHOOK_SECRET'): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function serviceSignature(timestamp: string, body: string): string {
  const root = requireEnv('OPENAI_WEBHOOK_SECRET');
  const key = createHmac('sha256', root).update(DOMAIN).digest();
  return createHmac('sha256', key).update(`${timestamp}.${body}`).digest('hex');
}

async function backendTool(
  organizationId: number,
  toolName: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const body = JSON.stringify({ organization_id: organizationId, tool_name: toolName, arguments: args });
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const response = await fetch(`${BACKEND_URL}/agentic-voice/internal/tool`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Sahjony-Voice-Timestamp': timestamp,
      'X-Sahjony-Voice-Signature': serviceSignature(timestamp, body),
    },
    body,
    cache: 'no-store',
    signal: AbortSignal.timeout(15000),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`Voice backend tool ${toolName} failed (${response.status})`);
  }
  return (payload?.result || payload) as Record<string, unknown>;
}

async function transferRealtimeCall(callId: string, target: string): Promise<void> {
  const response = await fetch(`https://api.openai.com/v1/realtime/calls/${encodeURIComponent(callId)}/refer`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${requireEnv('OPENAI_API_KEY')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ target_uri: `tel:${target}` }),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`Realtime transfer failed (${response.status})`);
}

export function buildAgenticVoiceAgent(context: VoiceRuntimeContext): RealtimeAgent {
  const callBackend = (name: string, args: Record<string, unknown>) =>
    backendTool(context.organizationId, name, args);

  const resolveLead = tool({
    name: 'resolve_lead_by_phone',
    description: 'Resolve the inbound caller to exactly one tenant-scoped CRM lead. Never guess on zero or multiple matches.',
    parameters: z.object({ phone: z.string() }),
    async execute({ phone }) {
      return callBackend('resolve_lead_by_phone', { phone });
    },
  });

  const getLeadContext = tool({
    name: 'get_lead_context',
    description: 'Read tenant-scoped lead and property context. Seller statements are not verified property facts.',
    parameters: z.object({ lead_id: z.number().int().positive() }),
    async execute({ lead_id }) {
      return callBackend('get_lead_context', { lead_id });
    },
  });

  const getSellerMemory = tool({
    name: 'get_seller_memory',
    description: 'Recall prior seller-stated qualification pillars and previous voice activity so questions are not repeated unnecessarily.',
    parameters: z.object({ lead_id: z.number().int().positive() }),
    async execute({ lead_id }) {
      return callBackend('get_seller_memory', { lead_id });
    },
  });

  const getCallPolicy = tool({
    name: 'get_call_policy',
    description: 'Read the jurisdiction-aware operational call policy. Unknown state fails closed.',
    parameters: z.object({ lead_id: z.number().int().positive() }),
    async execute({ lead_id }) {
      return callBackend('get_call_policy', { lead_id });
    },
  });

  const savePillars = tool({
    name: 'save_seller_pillars',
    description: 'Save only seller-stated Motivation, Timeline, Condition, and Price. Use null for anything not stated.',
    parameters: z.object({
      lead_id: z.number().int().positive(),
      motivation: z.string().nullable(),
      timeline_days: z.number().int().nullable(),
      condition: z.string().nullable(),
      seller_price: z.number().nullable(),
      summary: z.string(),
    }),
    async execute(args) {
      return callBackend('save_seller_pillars', args);
    },
  });

  const followUp = tool({
    name: 'create_follow_up',
    description: 'Create a supervised CRM follow-up task only. This does not contact the seller.',
    parameters: z.object({
      lead_id: z.number().int().positive(),
      title: z.string(),
      priority: z.number().int().min(1).max(100),
      notes: z.string(),
    }),
    async execute(args) {
      return callBackend('create_follow_up', args);
    },
  });

  const underwriting = tool({
    name: 'request_underwriting',
    description: 'Queue source-backed verification and underwriting. This never creates or communicates an offer.',
    parameters: z.object({ lead_id: z.number().int().positive(), reason: z.string() }),
    async execute(args) {
      return callBackend('request_underwriting', args);
    },
  });

  const escalate = tool({
    name: 'escalate_to_human',
    description: 'Transfer a motivated or complex seller to the configured human acquisitions number.',
    parameters: z.object({ lead_id: z.number().int().positive().nullable(), reason: z.string() }),
    async execute(args) {
      const result = await callBackend('escalate_to_human', args);
      const target = typeof result.transfer_target === 'string' ? result.transfer_target : TRANSFER_TARGET;
      await transferRealtimeCall(context.callId, target);
      return { ...result, transfer_started: true };
    },
  });

  const callerInstruction = context.callerPhone
    ? `The inbound caller number is ${context.callerPhone}. Resolve it early with resolve_lead_by_phone before assuming identity.`
    : 'The caller phone number was not available from SIP headers. Do not guess identity; ask for the property address naturally.';

  return new RealtimeAgent({
    name: 'SAHJONY Nationwide Acquisition Agent',
    instructions: [
      'You are SAHJONY’s bilingual English/Spanish wholesale real-estate acquisition voice agent for the United States.',
      'Speak naturally, concisely, and professionally. Identify yourself as an AI/automated assistant at the beginning of the conversation.',
      callerInstruction,
      'Your acquisition objective is to capture explicit Motivation, Timeline, Condition, and Price while understanding objections and urgency.',
      'Use CRM memory and jurisdiction policy before repeating known questions. Seller statements remain unverified claims.',
      'Never invent ownership, liens, ARV, comps, repairs, title status, legal outcomes, or facts the seller did not state.',
      'Never make a binding offer, execute a contract, move money, clear title, or autonomously initiate outbound contact.',
      'For motivated sellers, creative-finance discussions, title/legal complexity, or a direct human request, use escalate_to_human.',
      'If the seller asks not to be contacted, acknowledge the request, do not persuade further, and end the sales conversation.',
    ].join(' '),
    tools: [resolveLead, getLeadContext, getSellerMemory, getCallPolicy, savePillars, followUp, underwriting, escalate],
  });
}

export function realtimeSessionOptions() {
  return {
    model: MODEL,
    config: {
      outputModalities: ['audio'],
      parallelToolCalls: true,
      audio: {
        input: {
          transcription: { model: 'gpt-4o-mini-transcribe' },
          turnDetection: { type: 'semantic_vad', interruptResponse: true },
        },
        output: { voice: VOICE },
      },
    },
    workflowName: 'SAHJONY Nationwide Agentic Voice',
    traceMetadata: { system: 'sahjony_wholesale_os', channel: 'sip' },
  } as const;
}

export async function acceptAgenticSipCall(context: VoiceRuntimeContext): Promise<void> {
  const openai = new OpenAI({
    apiKey: requireEnv('OPENAI_API_KEY'),
    webhookSecret: requireEnv('OPENAI_WEBHOOK_SECRET'),
  });
  const agent = buildAgenticVoiceAgent(context);
  const options = realtimeSessionOptions();
  const initialConfig = await OpenAIRealtimeSIP.buildInitialConfig(agent, options as any);
  await openai.realtime.calls.accept(context.callId, initialConfig as any);
}

export async function runAgenticSipSession(
  context: VoiceRuntimeContext,
  maxRuntimeMs = 230 * 1000,
  startWithGreeting = true,
): Promise<{ reason: 'disconnected' | 'timeout' }> {
  const agent = buildAgenticVoiceAgent(context);
  const transport = new OpenAIRealtimeSIP();
  const session = new RealtimeSession(agent, { transport, ...(realtimeSessionOptions() as any) });

  let timeout: ReturnType<typeof setTimeout> | undefined;
  const finished = new Promise<{ reason: 'disconnected' | 'timeout' }>((resolve, reject) => {
    transport.once('disconnected', () => resolve({ reason: 'disconnected' }));
    transport.on('error', (error) => reject(error));
    timeout = setTimeout(() => resolve({ reason: 'timeout' }), maxRuntimeMs);
  });

  try {
    await session.connect({ apiKey: requireEnv('OPENAI_API_KEY'), callId: context.callId });
    if (startWithGreeting) {
      transport.sendEvent({
        type: 'response.create',
        response: { instructions: 'Greet the caller, disclose that you are an AI assistant for SAHJONY, and ask how you can help with the property.' },
      } as any);
    }
    return await finished;
  } finally {
    if (timeout) clearTimeout(timeout);
    // OpenAIRealtimeSIP.close() closes only this WebSocket attachment. It does
    // not issue a Realtime Calls hangup, allowing the next durable slice to
    // attach to the same existing SIP call by callId.
    transport.close();
  }
}

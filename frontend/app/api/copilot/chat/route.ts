import { NextRequest, NextResponse } from 'next/server';

export const maxDuration = 300;

const SYSTEM_PROMPT = `You are SAHJONY Wholesale Copilot operating inside a supervised real-estate wholesale operating system.
Use the supplied SAHJONY workspace context before making assumptions about existing properties, buyers, or skills. Use web search for current external research and file search for authorized knowledge when available.
Never invent owners, deeds, APNs, court records, liens, comparable sales, repair costs, buyer proof of funds, seller prices, or contact details.
Separate verified facts, provider estimates, seller/listing claims, screening assumptions, and AI inference.
The 70% rule is screening only, not an appraisal or authorization to offer.
Do not send offers, sign contracts, move money, or make legal/financial commitments. Human approval is required.
For material recommendations, state evidence, unknowns, and next checkable action.`;

const MAX_CONTEXT_CHARS = 30_000;
const OPENAI_TIMEOUT_MS = 280_000;
const MAX_ITEMS_PER_ARRAY = 20;
const MAX_STRING_CHARS = 800;
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

function outputText(response: any): string {
  if (typeof response?.output_text === 'string') return response.output_text;
  const parts: string[] = [];
  for (const item of response?.output || []) {
    if (item?.type !== 'message') continue;
    for (const content of item?.content || []) {
      if (content?.type === 'output_text' && typeof content?.text === 'string') parts.push(content.text);
    }
  }
  return parts.join('\n');
}

function actualTools(response: any) {
  const names = new Set<string>();
  for (const item of response?.output || []) {
    if (item?.type === 'web_search_call') names.add('web_search');
    if (item?.type === 'file_search_call') names.add('file_search');
  }
  return Array.from(names).map(name => ({ name }));
}

function sourcesFromResponse(response: any) {
  const webSeen = new Set<string>();
  const fileSeen = new Set<string>();
  const webSources: Array<{ type: string; url: string; title?: string }> = [];
  const fileSources: Array<{ type: string; file_id?: string; filename?: string }> = [];

  const addWeb = (url: unknown, title?: unknown) => {
    if (typeof url !== 'string' || !url || webSeen.has(url)) return;
    webSeen.add(url);
    webSources.push({ type: 'url', url, ...(typeof title === 'string' && title ? { title } : {}) });
  };

  for (const item of response?.output || []) {
    if (item?.type === 'web_search_call') {
      for (const source of item?.action?.sources || []) addWeb(source?.url, source?.title);
    }
    if (item?.type !== 'message') continue;
    for (const content of item?.content || []) {
      for (const annotation of content?.annotations || []) {
        if (annotation?.type === 'url_citation') addWeb(annotation?.url, annotation?.title);
        if (annotation?.type === 'file_citation') {
          const key = `${annotation?.file_id || ''}:${annotation?.filename || ''}`;
          if (!fileSeen.has(key)) {
            fileSeen.add(key);
            fileSources.push({ type: 'file', file_id: annotation?.file_id, filename: annotation?.filename });
          }
        }
      }
    }
  }
  return { webSources, fileSources };
}

function compact(value: unknown, depth = 0): unknown {
  if (depth > 5) return '[depth-limited]';
  if (typeof value === 'string') return value.length > MAX_STRING_CHARS ? `${value.slice(0, MAX_STRING_CHARS)}…` : value;
  if (Array.isArray(value)) {
    const items = value.slice(0, MAX_ITEMS_PER_ARRAY).map(item => compact(item, depth + 1));
    if (value.length > MAX_ITEMS_PER_ARRAY) items.push(`[${value.length - MAX_ITEMS_PER_ARRAY} more items omitted]`);
    return items;
  }
  if (value && typeof value === 'object') {
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) output[key] = compact(item, depth + 1);
    return output;
  }
  return value;
}

async function requireOwner(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie.includes('sahjony_owner_session=')) return { ok: false as const, status: 401, principal: null };
  try {
    const response = await fetch(new URL('/api/owner-access/session', request.url), {
      cache: 'no-store',
      headers: { cookie },
      signal: AbortSignal.timeout(10_000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.authenticated) return { ok: false as const, status: response.status === 503 ? 503 : 401, principal: null };
    const principal = data.principal || null;
    const role = String(principal?.role || '').toLowerCase();
    if ((ROLE_RANK[role] || 0) < ROLE_RANK.acquisitions) return { ok: false as const, status: 403, principal };
    return { ok: true as const, status: 200, principal };
  } catch {
    return { ok: false as const, status: 503, principal: null };
  }
}

function forwardedAuth(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  const authorization = request.headers.get('authorization') || '';
  return { cookie, authorization };
}

async function writeAudit(request: NextRequest, payload: Record<string, unknown>) {
  const { cookie, authorization } = forwardedAuth(request);
  const response = await fetch(new URL('/api/backend/crm/activities', request.url), {
    method: 'POST',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      cookie,
      ...(authorization ? { authorization } : {}),
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(10_000),
  });
  return response.ok;
}

async function workspaceContext(request: NextRequest) {
  const { cookie, authorization } = forwardedAuth(request);
  const paths = [
    '/api/backend/wholesale-os/skills',
    '/api/backend/wholesale-os/deal-factory',
    '/api/backend/workspace/buyers',
  ];

  const results = await Promise.all(paths.map(async path => {
    try {
      const response = await fetch(new URL(path, request.url), {
        cache: 'no-store',
        headers: { cookie, ...(authorization ? { authorization } : {}) },
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) return { path, available: false, status: response.status };
      return { path, available: true, data: compact(await response.json()) };
    } catch (error) {
      return { path, available: false, error: error instanceof Error ? error.message : 'request failed' };
    }
  }));

  const serialized = JSON.stringify(results);
  return {
    items: results,
    serialized: serialized.length > MAX_CONTEXT_CHARS ? `${serialized.slice(0, MAX_CONTEXT_CHARS)}\n[workspace context truncated]` : serialized,
    truncated: serialized.length > MAX_CONTEXT_CHARS,
  };
}

export async function POST(request: NextRequest) {
  const owner = await requireOwner(request);
  if (!owner.ok) {
    const detail = owner.status === 503 ? 'Owner session validation unavailable' : owner.status === 403 ? 'Acquisitions role or higher required' : 'Owner session required';
    return NextResponse.json(
      { detail },
      { status: owner.status, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } },
    );
  }

  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return NextResponse.json({ detail: 'OPENAI_API_KEY is not configured in this Vercel project' }, { status: 503 });

  const payload = await request.json().catch(() => ({}));
  const message = String(payload?.message || '').trim();
  if (!message) return NextResponse.json({ detail: 'message is required' }, { status: 422 });
  if (message.length > 20_000) return NextResponse.json({ detail: 'message is too long' }, { status: 422 });

  const auditStarted = await writeAudit(request, {
    activity_type: 'openai_wholesale_copilot_requested',
    summary: 'Wholesale Copilot analysis requested',
    metadata: { runtime: 'nextjs_same_origin', message_chars: message.length },
  }).catch(() => false);
  if (!auditStarted) {
    return NextResponse.json({ detail: 'Copilot audit service unavailable; request was not sent to OpenAI' }, { status: 503 });
  }

  const context = await workspaceContext(request);
  const tools: any[] = [{ type: 'web_search' }];
  if (process.env.OPENAI_VECTOR_STORE_ID) tools.push({ type: 'file_search', vector_store_ids: [process.env.OPENAI_VECTOR_STORE_ID] });

  let openaiResponse: Response;
  try {
    openaiResponse = await fetch('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: process.env.OPENAI_MODEL || 'gpt-5.6-sol',
        instructions: SYSTEM_PROMPT,
        tools,
        max_output_tokens: 4_500,
        input: `Operator request:\n${message}\n\nCurrent SAHJONY workspace context (source-bounded; unavailable sections must not be guessed):\n${context.serialized}`,
      }),
      signal: AbortSignal.timeout(OPENAI_TIMEOUT_MS),
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === 'TimeoutError';
    await writeAudit(request, {
      activity_type: 'openai_wholesale_copilot_failed',
      summary: timedOut ? 'Wholesale Copilot request timed out safely' : 'Wholesale Copilot network request failed',
      metadata: { runtime: 'nextjs_same_origin', failure: timedOut ? 'timeout' : 'network_error' },
    }).catch(() => false);
    return NextResponse.json({
      detail: timedOut
        ? 'Copilot research exceeded the bounded response window. No action was taken. Retry with fewer properties or a narrower verification request.'
        : 'Copilot could not reach OpenAI. No action was taken; retry once.',
    }, { status: timedOut ? 504 : 502, headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' } });
  }

  const data = await openaiResponse.json().catch(() => ({}));
  if (!openaiResponse.ok) {
    await writeAudit(request, {
      activity_type: 'openai_wholesale_copilot_failed',
      summary: 'Wholesale Copilot OpenAI request failed',
      metadata: { runtime: 'nextjs_same_origin', http_status: openaiResponse.status },
    }).catch(() => false);
    const detail = data?.error?.message || data?.detail || `OpenAI request failed (${openaiResponse.status})`;
    return NextResponse.json({ detail }, { status: openaiResponse.status });
  }

  const toolsUsed = actualTools(data);
  const { webSources, fileSources } = sourcesFromResponse(data);
  const auditCompleted = await writeAudit(request, {
    activity_type: 'openai_wholesale_copilot_completed',
    summary: 'Wholesale Copilot analysis completed',
    metadata: {
      runtime: 'nextjs_same_origin',
      response_id: data.id,
      model: data.model || process.env.OPENAI_MODEL || 'gpt-5.6-sol',
      tools_used: toolsUsed,
      web_source_count: webSources.length,
      file_source_count: fileSources.length,
      workspace_context_truncated: context.truncated,
    },
  }).catch(() => false);

  return NextResponse.json({
    response_id: data.id,
    model: data.model || process.env.OPENAI_MODEL || 'gpt-5.6-sol',
    answer: outputText(data),
    tools_used: toolsUsed,
    web_sources: webSources,
    file_sources: fileSources,
    workspace_context: context.items.map(item => ({ path: item.path, available: item.available, status: (item as any).status || null })),
    runtime: 'nextjs_same_origin',
    audit_persisted: auditCompleted,
    safety: {
      research_and_analysis: true,
      outbound_contact: false,
      offer_submission: false,
      contract_execution: false,
      payments: false,
      human_approval_required: true,
    },
  }, {
    headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' },
  });
}

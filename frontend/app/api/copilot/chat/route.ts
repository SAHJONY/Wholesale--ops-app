import { NextRequest, NextResponse } from 'next/server';

const SYSTEM_PROMPT = `You are SAHJONY Wholesale Copilot operating inside a supervised real-estate wholesale operating system.
Use the supplied SAHJONY workspace context before making assumptions about existing properties, buyers, or skills. Use web search for current external research and file search for authorized knowledge when available.
Never invent owners, deeds, APNs, court records, liens, comparable sales, repair costs, buyer proof of funds, seller prices, or contact details.
Separate verified facts, provider estimates, seller/listing claims, screening assumptions, and AI inference.
The 70% rule is screening only, not an appraisal or authorization to offer.
Do not send offers, sign contracts, move money, or make legal/financial commitments. Human approval is required.
For material recommendations, state evidence, unknowns, and next checkable action.`;

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

function fileSources(response: any) {
  const seen = new Set<string>();
  const sources: Array<{ type: string; file_id?: string; filename?: string }> = [];
  for (const item of response?.output || []) {
    if (item?.type !== 'message') continue;
    for (const content of item?.content || []) {
      for (const annotation of content?.annotations || []) {
        if (annotation?.type !== 'file_citation') continue;
        const key = `${annotation.file_id || ''}:${annotation.filename || ''}`;
        if (seen.has(key)) continue;
        seen.add(key);
        sources.push({ type: 'file', file_id: annotation.file_id, filename: annotation.filename });
      }
    }
  }
  return sources;
}

async function workspaceContext(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  const auth = request.headers.get('authorization') || 'Bearer cookie-session';
  const paths = [
    '/api/backend/wholesale-os/skills',
    '/api/backend/wholesale-os/deal-factory',
    '/api/backend/buyers',
  ];

  const results = await Promise.all(paths.map(async path => {
    try {
      const response = await fetch(new URL(path, request.url), {
        cache: 'no-store',
        headers: { cookie, authorization: auth },
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) return { path, available: false, status: response.status };
      return { path, available: true, data: await response.json() };
    } catch (error) {
      return { path, available: false, error: error instanceof Error ? error.message : 'request failed' };
    }
  }));

  return results;
}

export async function POST(request: NextRequest) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ detail: 'OPENAI_API_KEY is not configured in this Vercel project' }, { status: 503 });
  }

  const payload = await request.json().catch(() => ({}));
  const message = String(payload?.message || '').trim();
  if (!message) return NextResponse.json({ detail: 'message is required' }, { status: 422 });
  if (message.length > 20000) return NextResponse.json({ detail: 'message is too long' }, { status: 422 });

  const context = await workspaceContext(request);
  const tools: any[] = [{ type: 'web_search' }];
  if (process.env.OPENAI_VECTOR_STORE_ID) {
    tools.push({ type: 'file_search', vector_store_ids: [process.env.OPENAI_VECTOR_STORE_ID] });
  }

  const openaiResponse = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || 'gpt-5',
      instructions: SYSTEM_PROMPT,
      tools,
      input: `Operator request:\n${message}\n\nCurrent SAHJONY workspace context (source-bounded; unavailable sections must not be guessed):\n${JSON.stringify(context)}`,
    }),
    signal: AbortSignal.timeout(120000),
  });

  const data = await openaiResponse.json().catch(() => ({}));
  if (!openaiResponse.ok) {
    const detail = data?.error?.message || data?.detail || `OpenAI request failed (${openaiResponse.status})`;
    return NextResponse.json({ detail }, { status: openaiResponse.status });
  }

  return NextResponse.json({
    response_id: data.id,
    model: data.model || process.env.OPENAI_MODEL || 'gpt-5',
    answer: outputText(data),
    tools_used: [
      { name: 'web_search' },
      ...(process.env.OPENAI_VECTOR_STORE_ID ? [{ name: 'file_search' }] : []),
      { name: 'workspace_context_snapshot' },
    ],
    web_sources: [],
    file_sources: fileSources(data),
    workspace_context: context.map(item => ({ path: item.path, available: item.available, status: (item as any).status || null })),
    runtime: 'nextjs_same_origin',
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

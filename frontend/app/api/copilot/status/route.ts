import { NextResponse } from 'next/server';

export async function GET() {
  return NextResponse.json({
    configured: Boolean(process.env.OPENAI_API_KEY),
    model: process.env.OPENAI_MODEL || 'gpt-5',
    responses_api: true,
    tools: {
      web_search: true,
      file_search: Boolean(process.env.OPENAI_VECTOR_STORE_ID),
      workspace_functions: [
        'list_wholesale_skills',
        'list_deal_factory_candidates',
        'analyze_workspace_property',
        'list_verified_buyers',
      ],
      computer_use: false,
      realtime_voice: false,
    },
    runtime: 'nextjs_same_origin',
    note: 'OpenAI credentials are read from the same Vercel project that serves the Wholesale OS frontend.',
  }, {
    headers: { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' },
  });
}

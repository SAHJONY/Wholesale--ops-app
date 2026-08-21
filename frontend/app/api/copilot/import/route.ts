import { NextRequest, NextResponse } from 'next/server';

export const maxDuration = 120;

const EXTRACTION_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { candidates: { type: 'array', maxItems: 50, items: {
    type: 'object', additionalProperties: false,
    properties: {
      address:{type:'string'}, city:{type:'string'}, state:{type:'string'}, zip_code:{type:'string'},
      asking_price:{anyOf:[{type:'number'},{type:'null'}]}, property_type:{type:'string'},
      source_url:{type:'string'}, source_title:{type:'string'},
      listing_claims:{type:'array',items:{type:'string'},maxItems:12},
    },
    required:['address','city','state','zip_code','asking_price','property_type','source_url','source_title','listing_claims'],
  }}}, required:['candidates'],
};

function outputText(response: any): string {
  if (typeof response?.output_text === 'string') return response.output_text;
  for (const item of response?.output || []) for (const content of item?.content || []) if (content?.type === 'output_text') return content.text || '';
  return '';
}

export async function POST(request: NextRequest) {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie.includes('sahjony_owner_session=')) return NextResponse.json({detail:'Owner session required'},{status:401});
  const payload = await request.json().catch(() => ({}));
  const answer = String(payload?.answer || '').slice(0,40_000);
  const responseId = String(payload?.response_id || '').slice(0,200);
  const sources = Array.isArray(payload?.web_sources) ? payload.web_sources.slice(0,50) : [];
  if (!answer) return NextResponse.json({detail:'Copilot answer is required'},{status:422});
  if (!process.env.OPENAI_API_KEY) return NextResponse.json({detail:'OPENAI_API_KEY is not configured'},{status:503});

  let extraction: Response;
  try {
    extraction = await fetch('https://api.openai.com/v1/responses', {
      method:'POST', headers:{Authorization:`Bearer ${process.env.OPENAI_API_KEY}`,'Content-Type':'application/json'},
      body:JSON.stringify({
        model:process.env.OPENAI_MODEL || 'gpt-5.6-sol',
        instructions:'Extract only real property candidates explicitly identified in the research. Every candidate must have a complete US street address and a matching public source URL from the supplied sources. Infer city/state only when the research explicitly establishes the market. Never invent an owner, phone, email, ARV, repair cost, or missing address. Return no candidate when evidence is insufficient.',
        input:`Copilot research:\n${answer}\n\nAllowed public sources:\n${JSON.stringify(sources)}`,
        max_output_tokens:2500,
        text:{format:{type:'json_schema',name:'copilot_lead_candidates',strict:true,schema:EXTRACTION_SCHEMA}},
      }), signal:AbortSignal.timeout(90_000),
    });
  } catch {
    return NextResponse.json({detail:'Candidate extraction timed out safely; no leads were saved'},{status:504});
  }
  const extractionBody = await extraction.json().catch(() => ({}));
  if (!extraction.ok) return NextResponse.json({detail:extractionBody?.error?.message || `Candidate extraction failed (${extraction.status})`},{status:502});
  let candidates: unknown[] = [];
  try { candidates = JSON.parse(outputText(extractionBody)).candidates || []; }
  catch { return NextResponse.json({detail:'Candidate extraction returned invalid structured data'},{status:502}); }

  const backend = await fetch(new URL('/api/backend/openai-copilot/import-candidates',request.url), {
    method:'POST',cache:'no-store',headers:{'Content-Type':'application/json',cookie},
    body:JSON.stringify({response_id:responseId,candidates}),signal:AbortSignal.timeout(25_000),
  });
  const result = await backend.json().catch(() => ({}));
  return NextResponse.json(result,{status:backend.status,headers:{'Cache-Control':'no-store','X-Robots-Tag':'noindex'}});
}

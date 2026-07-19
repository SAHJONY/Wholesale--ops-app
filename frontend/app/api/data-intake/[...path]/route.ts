import { NextRequest, NextResponse } from 'next/server';

const BACKEND = 'https://backend-pi-opal-65.vercel.app';
const ALLOWED = new Set(['snapshot', 'preview', 'commit']);

function setupSnapshot() {
  return {
    status: 'setup',
    generated_at: new Date().toISOString(),
    required_columns: ['seller_name', 'phone', 'address', 'city', 'state', 'zip_code'],
    optional_columns: ['email', 'source', 'notes', 'asking_price', 'arv', 'repairs', 'bedrooms', 'bathrooms', 'sqft', 'motivation_score', 'distress_score', 'equity_score'],
    max_rows: 5000,
    texas_excluded: true,
    imports: [],
    detail: 'Data Intake API is not deployed on the backend yet.',
  };
}

async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const route = path.join('/');
  if (!ALLOWED.has(route)) {
    return NextResponse.json({ detail: 'Unsupported data-intake route' }, { status: 404 });
  }

  const auth = request.headers.get('authorization');
  if (!auth?.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ detail: 'Owner session required' }, { status: 401 });
  }

  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text();

  try {
    const response = await fetch(`${BACKEND}/data-intake/${route}`, {
      method: request.method,
      headers: { Authorization: auth, 'Content-Type': 'application/json' },
      body: body || undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    });

    const text = await response.text();

    if (response.status === 404) {
      if (route === 'snapshot') return NextResponse.json(setupSnapshot());
      return NextResponse.json(
        { detail: 'Data Intake API is not deployed on the backend yet. Redeploy the backend from latest main, then retry.' },
        { status: 503 },
      );
    }

    return new NextResponse(text || null, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    if (route === 'snapshot') return NextResponse.json(setupSnapshot());
    return NextResponse.json(
      { detail: `Data Intake backend unavailable: ${error instanceof Error ? error.message : 'request failed'}` },
      { status: 502 },
    );
  }
}

export const GET = handler;
export const POST = handler;

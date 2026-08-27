import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || process.env.BACKEND_URL || 'http://localhost:8000';
const CONNECT_URL = (process.env.SAHJONY_CONNECT_URL || 'https://sahjony-connect.vercel.app').replace(/\/$/, '');
const SESSION_COOKIE = 'sahjony_owner_session';

type Mode = 'text' | 'voice' | 'video';

type RequestBody = {
  mode?: Mode;
  contextId?: string;
  contactName?: string;
};

async function ownerSession(request: NextRequest) {
  const token = request.cookies.get(SESSION_COOKIE)?.value || '';
  if (!token) return null;
  try {
    const response = await fetch(`${BACKEND_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  const principal = await ownerSession(request);
  if (!principal) {
    return NextResponse.json({ detail: 'Valid owner session required' }, { status: 401 });
  }

  const key = process.env.SAHJONY_CONNECT_INTEGRATION_KEY?.trim();
  if (!key) {
    return NextResponse.json({ detail: 'SAHJONY Connect integration is not configured' }, { status: 503 });
  }

  let input: RequestBody = {};
  try { input = await request.json(); } catch {}
  const mode: Mode = input.mode === 'voice' || input.mode === 'video' ? input.mode : 'text';
  const contextId = String(input.contextId || 'owner-command-center').trim().slice(0, 240) || 'owner-command-center';
  const contactName = String(input.contactName || '').trim().slice(0, 180) || undefined;

  try {
    const upstream = await fetch(`${CONNECT_URL}/api/connect/integrations/session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Connect-Integration-Key': key,
      },
      body: JSON.stringify({
        project_id: 'wholesale_ops',
        project_name: 'SAHJONY Private Wholesale OS',
        external_context_id: contextId,
        context_type: contextId === 'owner-command-center' ? 'wholesale_operations' : 'real_estate_deal',
        display_name: contactName,
        language: 'auto',
        mode,
        ai_assistance: false,
      }),
      cache: 'no-store',
      signal: AbortSignal.timeout(20000),
    });

    const text = await upstream.text();
    return new NextResponse(text || null, {
      status: upstream.status,
      headers: {
        'Content-Type': upstream.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
      },
    });
  } catch {
    return NextResponse.json({ detail: 'SAHJONY Connect is temporarily unavailable' }, { status: 502 });
  }
}

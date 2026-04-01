import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const apiKey = process.env.BLAND_AI_API_KEY;
    if (!apiKey) {
      return NextResponse.json({ error: "BLAND_AI_API_KEY is missing" }, { status: 500 });
    }

    const body = await req.json();
    const phoneNumber = body?.phoneNumber as string | undefined;
    const task = body?.task as string | undefined;

    if (!phoneNumber) {
      return NextResponse.json({ error: "phoneNumber is required" }, { status: 400 });
    }

    const payload = {
      phone_number: phoneNumber,
      task:
        task ||
        "Introduce yourself as Alex Smith, a polished corporate acquisitions manager from a professional U.S. office. Sound fully human, calm, clear, and business-formal while still natural. Avoid hype/sales tone, avoid robotic cadence, and keep responses concise with confident executive phrasing. Be bilingual: continue in English or Spanish based on the person speaking. Ask about property condition, seller motivation, timeline, and best price. Keep tone respectful and businesslike. Do not proactively mention automation; if directly asked, respond honestly and keep focus on the deal.",
      voice: "30972a71-c4b5-4aa3-9ce7-e065d6409a8f",
      model: "base",
      from: process.env.BLAND_DEFAULT_FROM_NUMBER || process.env.BLAND_DEFAULT_CALLER_ID,
      wait_for_greeting: true,
    };

    const res = await fetch("https://api.bland.ai/v1/calls", {
      method: "POST",
      headers: {
        authorization: apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json({ error: "Bland call failed", details: data }, { status: res.status });
    }

    return NextResponse.json({ ok: true, data });
  } catch (error) {
    return NextResponse.json({ error: "Unexpected error", details: String(error) }, { status: 500 });
  }
}

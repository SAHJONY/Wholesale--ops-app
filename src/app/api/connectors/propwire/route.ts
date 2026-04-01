import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const targetUrl = body?.url || "https://propwire.com/search?filters=%7B%7D";

    const headers: Record<string, string> = {
      "User-Agent": "Mozilla/5.0 (compatible; OpenClaw-Connector/1.0)",
      Accept: "text/html,application/json",
    };

    const cookie = process.env.PROPWIRE_COOKIE;
    if (cookie) headers.Cookie = cookie;

    const res = await fetch(targetUrl, { headers });
    const html = await res.text();

    const hasAuthPrompt = /Log In|Sign Up|login/i.test(html);

    return NextResponse.json({
      ok: true,
      status: res.status,
      connected: true,
      authLikelyRequired: hasAuthPrompt,
      message: hasAuthPrompt
        ? "Propwire endpoint reachable, but authenticated session likely required for real lead data."
        : "Propwire endpoint reachable.",
      sample: html.slice(0, 1200),
    });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}

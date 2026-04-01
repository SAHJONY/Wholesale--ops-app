import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const hooksUrl = process.env.OPENCLAW_HOOKS_URL;
    const hooksToken = process.env.OPENCLAW_HOOKS_TOKEN;

    if (!hooksUrl || !hooksToken) {
      return NextResponse.json({ error: "OpenClaw hooks env is missing" }, { status: 500 });
    }

    const body = await req.json();
    const message = body?.message as string | undefined;
    const leads = body?.leads;

    if (!message) {
      return NextResponse.json({ error: "message is required" }, { status: 400 });
    }

    const prompt = `You are the in-app OpenClaw Brain for a wholesale real estate operating system.\n\nUser message: ${message}\n\nRecent lead payload:\n${JSON.stringify(
      leads || [],
    ).slice(0, 8000)}\n\nReturn concise, actionable guidance with next best action.`;

    const res = await fetch(hooksUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${hooksToken}`,
      },
      body: JSON.stringify({
        message: prompt,
        name: "AppBrain",
        agentId: "main",
        wakeMode: "now",
        deliver: false,
      }),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json({ error: "OpenClaw hooks request failed", details: data }, { status: res.status });
    }

    return NextResponse.json({ reply: "OpenClaw accepted the request. Response summary will appear in your main session shortly.", data });
  } catch (error) {
    return NextResponse.json({ error: "Unexpected error", details: String(error) }, { status: 500 });
  }
}

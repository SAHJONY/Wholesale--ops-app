import { NextResponse } from "next/server";

export async function GET() {
  try {
    const blandKey = process.env.BLAND_AI_API_KEY;

    let bland: any = { ok: false, message: "BLAND_AI_API_KEY missing" };
    if (blandKey) {
      const res = await fetch("https://api.bland.ai/v1/me", {
        headers: { authorization: blandKey },
      });
      const data = await res.json().catch(() => ({}));
      bland = {
        ok: res.ok,
        currentBalance:
          data?.billing?.current_balance ?? data?.current_balance ?? data?.balance ?? data?.credits ?? null,
        raw: data,
      };
    }

    return NextResponse.json({
      ok: true,
      bland,
      openclawApiKey: {
        ok: false,
        message:
          "Provider cash balance endpoint not configured yet. Add provider-specific balance integration (OpenAI/Anthropic/etc.) to enable live OpenClaw API-key balance.",
      },
      ts: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json({ ok: false, error: String(error) }, { status: 500 });
  }
}

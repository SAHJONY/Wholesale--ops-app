import { NextRequest, NextResponse } from "next/server";

type ConsoleResult = {
  ok: boolean;
  mode: "agent" | "wake";
  runId?: string;
  message: string;
  raw?: unknown;
};

export async function POST(req: NextRequest) {
  try {
    const hooksUrl = process.env.OPENCLAW_HOOKS_URL;
    const hooksToken = process.env.OPENCLAW_HOOKS_TOKEN;

    if (!hooksUrl || !hooksToken) {
      return NextResponse.json({ error: "OpenClaw hooks env missing" }, { status: 500 });
    }

    const { command } = (await req.json()) as { command?: string };
    if (!command?.trim()) {
      return NextResponse.json({ error: "command is required" }, { status: 400 });
    }

    const trimmed = command.trim();
    const hooksBase = hooksUrl.replace(/\/agent$/, "");

    let result: ConsoleResult;

    if (trimmed.startsWith("wake ")) {
      const text = trimmed.replace(/^wake\s+/, "");
      const res = await fetch(`${hooksBase}/wake`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${hooksToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text, mode: "now" }),
      });
      const data = await res.json().catch(() => ({}));
      result = {
        ok: res.ok,
        mode: "wake",
        message: res.ok ? `Wake event sent: ${text}` : "Wake event failed",
        raw: data,
      };
    } else {
      const prompt = `Console command from app: ${trimmed}\nReturn concise result.`;
      const res = await fetch(hooksUrl, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${hooksToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: prompt,
          name: "ConsoleAPI",
          agentId: "main",
          wakeMode: "now",
          deliver: false,
        }),
      });
      const data = await res.json().catch(() => ({}));
      result = {
        ok: res.ok,
        mode: "agent",
        runId: data?.runId,
        message: res.ok ? `Command accepted. runId=${data?.runId ?? "n/a"}` : "Command failed",
        raw: data,
      };
    }

    return NextResponse.json(result, { status: result.ok ? 200 : 500 });
  } catch (error) {
    return NextResponse.json({ error: "Unexpected error", details: String(error) }, { status: 500 });
  }
}

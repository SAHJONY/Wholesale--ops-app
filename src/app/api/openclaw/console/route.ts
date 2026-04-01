import { NextRequest, NextResponse } from "next/server";

type ConsoleResult = {
  ok: boolean;
  mode: "agent" | "wake";
  runId?: string;
  message: string;
  assistantReply?: string;
  raw?: unknown;
};

function quickAssistantReply(command: string, leads: any[], history: string[] = []) {
  const cmd = command.toLowerCase();
  const total = leads?.length || 0;
  const previous = history.length ? ` Previous context: ${history.slice(-2).join(" | ")}.` : "";
  if (cmd.includes("status")) return `System online. ${total} leads loaded. OpenClaw run queued.`;
  if (cmd.includes("pipeline")) return `Pipeline summary requested. I queued OpenClaw analysis and will prioritize the next best action.${previous}`;
  if (cmd.startsWith("wake ")) return `Wake event accepted. I nudged OpenClaw immediately.${previous}`;
  if (cmd.includes("offer") || cmd.includes("mao")) return `I’m running offer analysis now. I’ll target a conservative MAO and margin-safe range.${previous}`;
  return `Got it. I queued this in OpenClaw and I’m processing it as your operating console.${previous}`;
}

export async function POST(req: NextRequest) {
  try {
    const hooksUrl = process.env.OPENCLAW_HOOKS_URL;
    const hooksToken = process.env.OPENCLAW_HOOKS_TOKEN;

    if (!hooksUrl || !hooksToken) {
      return NextResponse.json({ error: "OpenClaw hooks env missing" }, { status: 500 });
    }

    const { command, leads, history } = (await req.json()) as { command?: string; leads?: unknown[]; history?: string[] };
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
        assistantReply: quickAssistantReply(trimmed, leads || [], history || []),
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
        assistantReply: quickAssistantReply(trimmed, leads || [], history || []),
        raw: data,
      };
    }

    return NextResponse.json(result, { status: result.ok ? 200 : 500 });
  } catch (error) {
    return NextResponse.json({ error: "Unexpected error", details: String(error) }, { status: 500 });
  }
}

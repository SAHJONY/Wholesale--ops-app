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
  const rows = Array.isArray(leads) ? leads : [];
  const total = rows.length;
  const pipeline = rows.reduce<Record<string, number>>((acc, row) => {
    const s = row?.status || "Lead In";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  const due = rows
    .filter((r) => r?.followUpDate && String(r.followUpDate) <= new Date().toISOString().slice(0, 10))
    .slice(0, 3)
    .map((r) => r.address)
    .filter(Boolean);

  const top = rows[0];
  const previous = history.length ? ` Previous context: ${history.slice(-2).join(" | ")}.` : "";
  if (cmd.includes("status")) {
    return `System online. Leads: ${total}. Follow-ups due today: ${due.length}. OpenClaw execution is active.${previous}`;
  }
  if (cmd.includes("pipeline")) {
    const breakdown = Object.entries(pipeline)
      .map(([k, v]) => `${k}:${v}`)
      .join(" | ");
    return `Pipeline summary: ${breakdown || "no leads yet"}.${previous}`;
  }
  if (cmd.startsWith("wake ")) return `Wake event accepted. I nudged OpenClaw immediately.${previous}`;
  if (cmd.includes("offer") || cmd.includes("mao")) {
    if (!top) return `No lead loaded yet. Add a lead with asking/ARV/rehab and rerun offer strategy.${previous}`;
    const ask = Number(top.asking || 0);
    const arv = Number(top.arv || 0);
    const rehab = Number(top.rehab || 0);
    const mao = arv * 0.7 - rehab;
    return `Offer model for ${top.address || "latest lead"}: Ask $${ask.toLocaleString()}, ARV $${arv.toLocaleString()}, Rehab $${rehab.toLocaleString()}, MAO $${Math.round(
      mao,
    ).toLocaleString()}.${previous}`;
  }
  if (cmd.includes("next") || cmd.includes("action")) {
    return `Next best action: ${due[0] ? `follow up ${due[0]} now` : "underwrite the newest lead and send first offer"}.${previous}`;
  }
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
      const bridgeUrl = process.env.OPENCLAW_REALTIME_BRIDGE_URL;
      const bridgeToken = process.env.OPENCLAW_REALTIME_BRIDGE_TOKEN;

      if (bridgeUrl && bridgeToken) {
        const bridgeRes = await fetch(bridgeUrl, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${bridgeToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ message: trimmed }),
        });

        if (bridgeRes.ok) {
          const bridgeData = await bridgeRes.json().catch(() => ({}));
          result = {
            ok: true,
            mode: "agent",
            message: bridgeData?.text || "Realtime bridge responded.",
            assistantReply: bridgeData?.text || quickAssistantReply(trimmed, leads || [], history || []),
            raw: bridgeData,
          };
          return NextResponse.json(result);
        }
      }

      const skillMatch = trimmed.match(/^skill:([a-zA-Z0-9-]+)\s+([\s\S]+)/);
      const prompt = skillMatch
        ? `Use the ${skillMatch[1]} skill for this request. Execute and return concise actionable output:\n${skillMatch[2]}`
        : trimmed.toLowerCase().startsWith("paperclip")
          ? `Use the Paperclip skill. Execute this operator intent and return concise actionable output:\n${trimmed}`
          : `Console command from app: ${trimmed}\nReturn concise result.`;
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

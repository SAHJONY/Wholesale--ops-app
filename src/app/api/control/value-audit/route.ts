import { NextResponse } from "next/server";

type Check = { name: string; ok: boolean; detail: string };

export async function GET() {
  const base = process.env.NEXT_PUBLIC_APP_BASE_URL || "https://app.sahjonycapital.com";
  const checks: Check[] = [];

  const testEndpoint = async (name: string, path: string) => {
    try {
      const res = await fetch(`${base}${path}`, { cache: "no-store" });
      const exists = res.ok || res.status === 405;
      checks.push({ name, ok: exists, detail: `${path} -> ${res.status}` });
    } catch (e) {
      checks.push({ name, ok: false, detail: `${path} -> ${String(e)}` });
    }
  };

  await Promise.all([
    testEndpoint("Bland call endpoint", "/api/bland/call"),
    testEndpoint("OpenClaw console endpoint", "/api/openclaw/console"),
    testEndpoint("Balance monitor endpoint", "/api/monitor/balance"),
    testEndpoint("Control snapshot endpoint", "/api/control/snapshot"),
  ]);

  const passed = checks.filter((c) => c.ok).length;
  const score = Math.round((passed / checks.length) * 100);

  return NextResponse.json({
    ok: true,
    score,
    passed,
    total: checks.length,
    checks,
    recommendations: [
      "Keep lead intake + tracker + offer workflow as core",
      "Keep call execution and callback brief workflow",
      "Keep cash/balance visibility always-on",
      "Remove any section that does not improve lead-to-contract throughput",
    ],
    ts: new Date().toISOString(),
  });
}

import { NextResponse } from "next/server";

const CONNECTORS = [
  "Propwire",
  "PropStream",
  "BatchLeads",
  "Zillow",
  "Realtor.com",
  "Redfin",
  "FSBO",
  "Facebook Marketplace",
  "County Records",
];

export async function GET() {
  try {
    const base = process.env.NEXT_PUBLIC_APP_BASE_URL || "https://app.sahjonycapital.com";
    const monitorRes = await fetch(`${base}/api/monitor/balance`, { cache: "no-store" }).catch(() => null);
    const monitor = monitorRes ? await monitorRes.json().catch(() => null) : null;

    return NextResponse.json({
      ok: true,
      business: "SAHJONY CAPITAL LLC",
      persona: "Alex Smith",
      policy: {
        transferCallsToOwner: false,
        objective: "Collect full seller intel and generate callback closing briefs",
      },
      balances: {
        bland: monitor?.bland || null,
        openclaw: monitor?.openclawApiKey || null,
      },
      connectors: CONNECTORS.map((name) => ({ name, status: "connector-ready" })),
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json({ ok: false, error: String(error) }, { status: 500 });
  }
}

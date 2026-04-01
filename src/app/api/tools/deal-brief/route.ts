import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const address = String(body?.address || "").trim();
    const phone = String(body?.phone || "").trim();
    const owner = String(body?.owner || "").trim();
    const intel = String(body?.intel || "").trim();
    const callId = String(body?.callId || "").trim();

    if (!address || !phone) {
      return NextResponse.json({ ok: false, error: "address and phone are required" }, { status: 400 });
    }

    const brief = [
      "CALLBACK BRIEF",
      `Address: ${address}`,
      `Phone: ${phone}`,
      `Owner: ${owner || "n/a"}`,
      `Call ID: ${callId || "n/a"}`,
      "",
      "Deal Intel:",
      intel || "No analyzer output captured.",
      "",
      "John Callback Objective:",
      "1) Confirm motivation and timeline",
      "2) Validate condition and risks",
      "3) Anchor on modeled offer strategy",
      "4) Negotiate lowest acceptable number",
      "5) Move to written offer follow-up",
    ].join("\n");

    return NextResponse.json({ ok: true, brief });
  } catch (error) {
    return NextResponse.json({ ok: false, error: String(error) }, { status: 500 });
  }
}

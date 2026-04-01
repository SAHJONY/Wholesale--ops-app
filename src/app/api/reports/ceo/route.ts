import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const apiKey = process.env.RESEND_API_KEY;
    const email = process.env.SMTP_USER;

    if (!apiKey || !email) {
      return NextResponse.json({ error: "Email env missing" }, { status: 500 });
    }

    const body = await req.json().catch(() => ({}));
    const report = body?.report || "No report content provided.";

    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: email,
        to: [email],
        subject: "Wholesale Ops CEO Report",
        text: report,
      }),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return NextResponse.json({ error: "Failed to send report", details: data }, { status: res.status });
    }

    return NextResponse.json({ ok: true, data });
  } catch (error) {
    return NextResponse.json({ error: "Unexpected error", details: String(error) }, { status: 500 });
  }
}

export async function GET() {
  const apiKey = process.env.RESEND_API_KEY;
  const email = process.env.SMTP_USER;

  if (!apiKey || !email) {
    return NextResponse.json({ error: "Email env missing" }, { status: 500 });
  }

  const text = `Automated daily CEO report trigger fired at ${new Date().toISOString()}.`;

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: email,
      to: [email],
      subject: "Daily Wholesale Ops Report Trigger",
      text,
    }),
  });

  const data = await res.json().catch(() => ({}));
  return NextResponse.json({ ok: res.ok, data }, { status: res.ok ? 200 : 500 });
}

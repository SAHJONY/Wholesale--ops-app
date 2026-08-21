import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const checks = {
    resend_api_key_configured: Boolean(process.env.RESEND_API_KEY),
    webhook_secret_configured: Boolean(process.env.RESEND_WEBHOOK_SECRET),
    default_organization_configured: Boolean(process.env.EMAIL_DEFAULT_ORGANIZATION_ID),
    domain_verified: (process.env.EMAIL_DOMAIN_VERIFIED ?? "").toLowerCase() === "true",
    inbound_verified: (process.env.EMAIL_INBOUND_VERIFIED ?? "").toLowerCase() === "true",
  };

  return NextResponse.json(
    {
      provider: "resend",
      domain: "sahjonycapitalllc.com",
      default_sender: "acquisitions@sahjonycapitalllc.com",
      checks,
      sending_live: checks.resend_api_key_configured && checks.domain_verified,
      responding_live: Object.values(checks).every(Boolean),
      fail_closed: true,
      secrets_exposed: false,
    },
    {
      status: 200,
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}

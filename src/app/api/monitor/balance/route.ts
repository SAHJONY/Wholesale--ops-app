import { NextResponse } from "next/server";

export async function GET() {
  try {
    const blandKey = process.env.BLAND_AI_API_KEY;
    const openaiKey = process.env.OPENAI_API_KEY;

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

    let openclawApiKey: any = {
      ok: false,
      provider: "openai",
      message:
        "OPENAI_API_KEY not found in app environment. Add it to enable live OpenAI balance/cost monitoring for OpenClaw.",
    };

    if (openaiKey) {
      try {
        const start = Math.floor(new Date(new Date().getFullYear(), new Date().getMonth(), 1).getTime() / 1000);
        const costsRes = await fetch(`https://api.openai.com/v1/organization/costs?start_time=${start}&bucket_width=1d`, {
          headers: { Authorization: `Bearer ${openaiKey}` },
        });
        const costsData = await costsRes.json().catch(() => ({}));

        const monthlySpent = Array.isArray(costsData?.data)
          ? costsData.data.reduce((sum: number, bucket: any) => {
              const bucketAmount = Array.isArray(bucket?.results)
                ? bucket.results.reduce((s: number, r: any) => s + Number(r?.amount?.value || 0), 0)
                : Number(bucket?.amount?.value || 0);
              return sum + bucketAmount;
            }, 0)
          : null;

        openclawApiKey = {
          ok: costsRes.ok,
          provider: "openai",
          monthlySpent,
          message: costsRes.ok
            ? "Live OpenAI monthly spend loaded (MTD)."
            : "OpenAI balance endpoint did not return spend; verify key permissions.",
          raw: costsData,
        };
      } catch (err) {
        openclawApiKey = {
          ok: false,
          provider: "openai",
          message: `OpenAI balance check failed: ${String(err)}`,
        };
      }
    }

    return NextResponse.json({
      ok: true,
      bland,
      openclawApiKey,
      ts: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json({ ok: false, error: String(error) }, { status: 500 });
  }
}

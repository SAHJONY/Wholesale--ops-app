import { NextRequest, NextResponse } from 'next/server';

// Production must use the Vercel service binding. BACKEND_URL is an explicit
// local/staging override only; never silently fall back to a retired backend.
const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';

type RealDeal = {
  property_id?: number;
  owner?: { name?: string; type?: string; mailing_address?: string; verified?: boolean };
  deed?: { parcel_id?: string; date?: string; consideration?: number; type?: string; instrument?: string };
  property?: {
    address?: string;
    city?: string;
    state?: string;
    zip_code?: string;
    property_type?: string;
    asking_price?: number;
    arv?: number;
    repairs?: number;
    distress_signals?: string[];
  };
  underwriting?: {
    target_contract_price?: number;
    target_buyer_price?: number;
    projected_assignment_fee?: number;
    meets_10k_target?: boolean;
    risk_score?: number;
  };
  sources?: Array<{ provider?: string; reference?: string; confidence?: number }>;
  source_confidence?: number;
  next_action?: string;
};

async function backendFetch(path: string, authorization: string | null) {
  return fetch(`${BACKEND_URL}${path}`, {
    method: 'GET',
    headers: authorization ? { Authorization: authorization } : {},
    cache: 'no-store',
    signal: AbortSignal.timeout(30000),
  });
}

function toOpportunity(deal: RealDeal, index: number) {
  const property = deal.property || {};
  const owner = deal.owner || {};
  const deed = deal.deed || {};
  const underwriting = deal.underwriting || {};
  const arv = Number(property.arv || 0);
  const repairs = Number(property.repairs || 0);
  const contractPrice = Number(underwriting.target_contract_price || property.asking_price || 0);
  const hasScreenInputs = arv > 0 && repairs >= 0;
  const screeningBuyerPrice = hasScreenInputs ? Math.max(0, arv * 0.7 - repairs) : undefined;
  const screeningSpread = screeningBuyerPrice !== undefined && contractPrice > 0
    ? screeningBuyerPrice - contractPrice
    : Number(underwriting.projected_assignment_fee || 0);
  const sources = Array.isArray(deal.sources) ? deal.sources : [];
  const sourceConfidence = Math.max(0, Math.min(1, Number(deal.source_confidence || 0)));
  const missing: string[] = [];

  if (!owner.name) missing.push('verified owner of record');
  if (!deed.parcel_id) missing.push('parcel/APN');
  if (!deed.date) missing.push('latest deed/transfer date');
  if (!property.arv) missing.push('source-backed ARV');
  if (property.repairs === undefined || property.repairs === null) missing.push('repair estimate');
  if (!contractPrice) missing.push('seller/contract price');
  if (!sources.length) missing.push('source references');

  const evidenceScore = Math.round(sourceConfidence * 100);
  const individualOwner = owner.type === 'individual';
  const meets10k = screeningSpread >= 10000;
  const ready = individualOwner && Boolean(owner.verified) && sources.length > 0 && meets10k && missing.length === 0;

  return {
    property: {
      id: Number(deal.property_id || index + 1),
      address: property.address || 'Address unavailable',
      city: property.city || '',
      state: property.state || '',
      zip_code: property.zip_code || '',
      property_type: property.property_type || 'unknown',
      asking_price: contractPrice || undefined,
      arv: property.arv,
      repairs: property.repairs,
      distress_signals: Array.isArray(property.distress_signals) ? property.distress_signals : [],
    },
    owner: {
      name: owner.name,
      type: owner.type || 'unknown',
      mailing_address: owner.mailing_address,
      verification_status: owner.verified ? 'verified' : 'unverified',
      confidence: sourceConfidence,
    },
    deed: {
      apn: deed.parcel_id,
      last_sale_date: deed.date,
      last_sale_price: deed.consideration,
      deed_type: deed.type,
      instrument: deed.instrument,
    },
    distress: {
      signals: Array.isArray(property.distress_signals) ? property.distress_signals : [],
      count: Array.isArray(property.distress_signals) ? property.distress_signals.length : 0,
    },
    economics: {
      screening_factor: 0.7,
      screening_buyer_price: screeningBuyerPrice,
      seller_price: contractPrice || undefined,
      projected_screening_spread: screeningSpread,
      meets_10k_target: meets10k,
      authority: hasScreenInputs ? '70_percent_screen_from_verified_real_deal_inputs' : 'verified_assignment_spread_fallback',
    },
    buyers: [],
    evidence: {
      score: evidenceScore,
      sources: sources.map(source => ({
        provider: source.provider || 'source',
        reference: source.reference,
        confidence: Number(source.confidence || 0),
        verification_status: 'verified',
      })),
      source_count: sources.length,
      open_conflicts: [],
      missing,
    },
    decision: {
      ready_for_promotion: ready,
      risk_score: Number(underwriting.risk_score ?? Math.max(0, 100 - evidenceScore)),
      next_action: deal.next_action || 'Re-verify title, comps, repair scope and buyer before any seller commitment.',
      human_offer_approval_required: true,
      legal_financial_actions_autonomous: false,
    },
  };
}

export async function GET(request: NextRequest) {
  const authorization = request.headers.get('authorization');

  try {
    const primary = await backendFetch('/wholesale-os/deal-factory', authorization);
    const primaryBody = await primary.text();
    if (primary.ok || primary.status === 401 || primary.status === 403) {
      return new NextResponse(primaryBody || null, {
        status: primary.status,
        headers: {
          'Content-Type': primary.headers.get('content-type') || 'application/json',
          'Cache-Control': 'no-store',
          'X-Deal-Factory-Mode': 'primary',
        },
      });
    }

    const fallback = await backendFetch('/wholesale/real-deals?property_type=single_family&owner_type=individual&min_assignment_fee=0', authorization);
    if (!fallback.ok) {
      return new NextResponse(primaryBody || JSON.stringify({ detail: `Deal Factory failed (${primary.status}) and verified-deals fallback failed (${fallback.status})` }), {
        status: primary.status,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      });
    }

    const fallbackData = await fallback.json().catch(() => ({ deals: [] }));
    const deals: RealDeal[] = Array.isArray(fallbackData?.deals) ? fallbackData.deals : [];
    const opportunities = deals.map(toOpportunity);
    opportunities.sort((a, b) => {
      if (a.decision.ready_for_promotion !== b.decision.ready_for_promotion) return a.decision.ready_for_promotion ? -1 : 1;
      return Number(b.economics.projected_screening_spread || 0) - Number(a.economics.projected_screening_spread || 0);
    });

    const payload = {
      generated_at: new Date().toISOString(),
      mode: 'fallback_verified_real_deals',
      degraded: true,
      fallback_reason: `Primary Deal Factory returned ${primary.status}`,
      summary: {
        prospects: opportunities.length,
        promotion_ready: opportunities.filter(item => item.decision.ready_for_promotion).length,
        individual_owned: opportunities.filter(item => item.owner.type === 'individual').length,
        meets_10k_screen: opportunities.filter(item => item.economics.meets_10k_target).length,
        buyers: 0,
        promoted_deals: opportunities.length,
      },
      opportunities,
      skills: [],
      operating_flow: [
        'Load verified real deals while Deal Factory backend is degraded',
        'Preserve owner/deed/source provenance',
        'Recompute 70% screening only when ARV and repairs are present',
        'Surface missing evidence instead of guessing',
        'Require human-controlled offer, contract and closing actions',
      ],
    };

    return NextResponse.json(payload, {
      status: 200,
      headers: {
        'Cache-Control': 'no-store',
        'X-Deal-Factory-Mode': 'fallback_verified_real_deals',
      },
    });
  } catch (error) {
    return NextResponse.json({
      detail: `Deal Factory unavailable: ${error instanceof Error ? error.message : 'request failed'}`,
    }, { status: 502, headers: { 'Cache-Control': 'no-store' } });
  }
}

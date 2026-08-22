'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './real-deals.module.css';

const SIGN_IN = '/login?returnTo=/owner/real-deals';

type PropertyView = {
  address?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  property_type?: string;
  arv?: number;
  repairs?: number;
  mao?: number;
};

type RealDeal = {
  deal_id: number;
  stage: string;
  property: PropertyView;
  owner: { name?: string; verified?: boolean };
  underwriting: {
    target_contract_price?: number;
    target_buyer_price?: number;
    projected_assignment_fee?: number;
    probability_to_close?: number;
    risk_score?: number;
  };
  next_action?: string;
  gate?: { cleared?: boolean; blockers?: string[]; owner_verified?: boolean; title_verified?: boolean; source_count?: number };
};

type DealDossier = {
  deal: {
    id: number;
    stage?: string;
    strategy?: string;
    probability_to_close?: number;
    risk_score?: number;
    next_action?: string;
    metadata?: Record<string, any>;
  };
  property: PropertyView & { id?: number; lead_id?: number; distress_signals?: unknown };
  lead?: { seller_name?: string; status?: string } | null;
  dossier?: {
    auction_date?: string;
    hard_blockers?: string[];
    underwriting?: Record<string, any>;
    completion_state?: string;
  };
};

type ListResponse = { count: number; deals: RealDeal[] };

function money(value?: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(Number(value || 0));
}

export default function RealDealsPage() {
  const [verifiedDeals, setVerifiedDeals] = useState<RealDeal[]>([]);
  const [opportunities, setOpportunities] = useState<DealDossier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const request = useCallback(async (path: string) => {
    const response = await fetch(`/api/backend${path}`, {
      cache: 'no-store',
      credentials: 'same-origin',
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      const sessionResponse = await fetch('/api/owner-access/session', {
        cache: 'no-store',
        credentials: 'same-origin',
      });
      const session = await sessionResponse.json().catch(() => ({}));
      if (!sessionResponse.ok || !session.authenticated) {
        window.location.replace(SIGN_IN);
        throw new Error('Owner session required');
      }
      throw new Error('Your owner session is valid, but the Deal Room service rejected this request. Stay on this page and review System Health if the problem persists.');
    }
    if (!response.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    }
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const strictQuery = new URLSearchParams({
        property_type: 'single_family',
        owner_type: 'individual',
        min_assignment_fee: '10000',
        verified_only: 'true',
      });
      const activeQuery = new URLSearchParams({
        property_type: 'single_family',
        min_assignment_fee: '0',
      });

      const [strictData, activeData] = await Promise.all([
        request(`/wholesale/real-deals?${strictQuery.toString()}`) as Promise<ListResponse>,
        request(`/wholesale/real-deals?${activeQuery.toString()}`) as Promise<ListResponse>,
      ]);

      setVerifiedDeals(Array.isArray(strictData.deals) ? strictData.deals : []);

      const candidateIds = Array.from(new Set((activeData.deals || []).map((deal) => deal.deal_id)));
      const dossiers = await Promise.all(
        candidateIds.map(async (dealId) => {
          try {
            return (await request(`/deal-dossier/${dealId}`)) as DealDossier;
          } catch {
            return null;
          }
        }),
      );

      setOpportunities(
        dossiers
          .filter((item): item is DealDossier => Boolean(item))
          .sort((a, b) => Number(b.deal.id || 0) - Number(a.deal.id || 0)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load real-deal workspace');
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    void load();
  }, [load]);

  const opportunityValue = useMemo(
    () => opportunities.reduce((sum, item) => sum + Number(item.deal.metadata?.preferred_underwriting_scenario?.assignment_fee || 0), 0),
    [opportunities],
  );

  const verifiedSpread = useMemo(
    () => verifiedDeals.reduce((sum, deal) => sum + Number(deal.underwriting.projected_assignment_fee || 0), 0),
    [verifiedDeals],
  );

  return (
    <main className={styles.page}>
      <header className={styles.hero}>
        <div>
          <span>SAHJONY WHOLESALE OS · REAL DEALS</span>
          <h1>Real opportunities first. Verified deals when the gates clear.</h1>
          <p>
            Active opportunities remain visible while ownership, title, repairs, compliance and buyer evidence are verified.
            Verification-stage deals are never mislabeled as contract-ready.
          </p>
        </div>
        <div className={styles.heroActions}>
          <Link href="/owner">CEO Command</Link>
          <button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh deals'}</button>
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      <section className={styles.kpis}>
        <article><span>Active real opportunities</span><strong>{opportunities.length}</strong><small>Source-backed · verification allowed</small></article>
        <article><span>Verified real deals</span><strong>{verifiedDeals.length}</strong><small>Strict owner + spread gate</small></article>
        <article><span>Opportunity assignment target</span><strong>{money(opportunityValue)}</strong><small>Scenario only until authorized</small></article>
        <article><span>Verified assignment spread</span><strong>{money(verifiedSpread)}</strong><small>Promoted deal economics</small></article>
      </section>

      <section className={styles.candidateSection}>
        <div className={styles.sectionTitle}>
          <div>
            <span>ACTIVE PIPELINE</span>
            <h2>Active real opportunities</h2>
            <p>These are real production opportunities already linked to the SAHJONY workspace. Open gates remain visible and enforceable.</p>
          </div>
        </div>
        <div className={styles.grid}>
          {opportunities.map((item) => {
            const meta = item.deal.metadata || {};
            const scenario = meta.preferred_underwriting_scenario || item.dossier?.underwriting || {};
            const blockers = item.dossier?.hard_blockers || meta.hard_blockers || [];
            const ownerCandidate = meta.owner_research?.leading_candidate || item.lead?.seller_name || 'Owner verification pending';
            return (
              <article className={`${styles.card} ${styles.candidateCard}`} key={item.deal.id}>
                <div className={styles.cardTop}>
                  <div>
                    <span>REAL OPPORTUNITY · DEAL #{item.deal.id}</span>
                    <h2>{item.property.address}</h2>
                    <p>{item.property.city}, {item.property.state} {item.property.zip_code}</p>
                  </div>
                  <strong>{money(scenario.assignment_fee)}</strong>
                </div>

                <div className={styles.badges}>
                  <span>{String(item.deal.stage || 'verification').toUpperCase()}</span>
                  <span>Source-backed</span>
                  <span>Not offer-authorized</span>
                  {item.dossier?.auction_date && <span>Auction {item.dossier.auction_date}</span>}
                </div>

                <div className={styles.metrics}>
                  <div><span>ARV</span><b>{scenario.arv ? money(scenario.arv) : 'Pending'}</b></div>
                  <div><span>Repairs</span><b>{scenario.repair_reserve ? money(scenario.repair_reserve) : item.property.repairs ? money(item.property.repairs) : 'Pending'}</b></div>
                  <div><span>MAO scenario</span><b>{scenario.mao ? money(scenario.mao) : 'Pending'}</b></div>
                  <div><span>Opening scenario</span><b>{scenario.opening_offer ? money(scenario.opening_offer) : 'Pending'}</b></div>
                  <div><span>Buyer target</span><b>{scenario.buyer_target ? money(scenario.buyer_target) : 'Pending'}</b></div>
                  <div><span>Assignment target</span><b className={styles.profit}>{scenario.assignment_fee ? money(scenario.assignment_fee) : 'Pending'}</b></div>
                </div>

                <div className={styles.ownerPanel}>
                  <div>
                    <span>OWNER / SELLER</span>
                    <b>{ownerCandidate}</b>
                    <small>{meta.communication_gate?.seller_authority_verified ? 'Authority verified' : 'Seller authority not yet verified'}</small>
                  </div>
                  <div>
                    <span>OPEN GATES</span>
                    <b>{blockers.length ? `${blockers.length} blocker${blockers.length === 1 ? '' : 's'}` : 'Verification in progress'}</b>
                    <small>{blockers.length ? blockers.join(' · ') : item.deal.next_action || 'Continue verification'}</small>
                  </div>
                </div>

                <footer>
                  <span>{item.deal.next_action || 'Continue source-backed verification.'}</span>
                  <Link href={`/owner/deals?deal=${item.deal.id}`}>Open Deal Room →</Link>
                </footer>
              </article>
            );
          })}

          {!loading && !opportunities.length && (
            <div className={styles.empty}>
              <h2>No active real opportunities are visible.</h2>
              <p>Only workspace-linked production opportunities marked as real/golden deals appear here.</p>
            </div>
          )}
        </div>
      </section>

      <section className={styles.candidateSection}>
        <div className={styles.sectionTitle}>
          <div>
            <span>VERIFIED PIPELINE</span>
            <h2>Verified real wholesale deals</h2>
            <p>These have passed owner authority, title/deed evidence, source, underwriting and minimum assignment-spread gates.</p>
          </div>
        </div>
        <div className={styles.grid}>
          {verifiedDeals.map((deal) => (
            <article className={styles.card} key={deal.deal_id}>
              <div className={styles.cardTop}>
                <div>
                  <span>VERIFIED DEAL #{deal.deal_id}</span>
                  <h2>{deal.property.address}</h2>
                  <p>{deal.property.city}, {deal.property.state} {deal.property.zip_code}</p>
                </div>
                <strong>{money(deal.underwriting.projected_assignment_fee)}</strong>
              </div>
              <div className={styles.badges}><span>Owner verified</span><span>Single-family</span><span>{deal.stage}</span></div>
              <div className={styles.metrics}>
                <div><span>ARV</span><b>{money(deal.property.arv)}</b></div>
                <div><span>Repairs</span><b>{money(deal.property.repairs)}</b></div>
                <div><span>Seller contract</span><b>{money(deal.underwriting.target_contract_price)}</b></div>
                <div><span>Buyer price</span><b>{money(deal.underwriting.target_buyer_price)}</b></div>
                <div><span>Assignment</span><b className={styles.profit}>{money(deal.underwriting.projected_assignment_fee)}</b></div>
                <div><span>Risk</span><b>{Math.round(Number(deal.underwriting.risk_score || 0))}</b></div>
              </div>
              <footer><span>{deal.next_action || 'Continue deal execution.'}</span><Link href={`/owner/deals?deal=${deal.deal_id}`}>Open Deal Room →</Link></footer>
            </article>
          ))}
          {!loading && !verifiedDeals.length && (
            <div className={styles.empty}>
              <h2>No deals have cleared the verified gate yet.</h2>
              <p>Active opportunities above remain visible while seller authority, title and underwriting evidence are completed.</p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

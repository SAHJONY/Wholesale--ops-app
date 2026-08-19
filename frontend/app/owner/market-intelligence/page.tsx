'use client';

import { useEffect, useMemo, useState } from 'react';
import styles from './market-intelligence.module.css';

type Market = {
  metro: string;
  state: string;
  tier: 'PRIORITY' | 'HOT' | 'WATCH';
  score: number;
  cashBuyer: number;
  institutional: number;
  wholesalerLiquidity: number;
  affordability: number;
  signal: string;
  focus: string;
  source: string;
};

type BuyerDirectory = {
  summary?: {
    total_buyers?: number;
    localized_buyers?: number;
    proof_of_funds_verified?: number;
    cash_buyer_candidates?: number;
    cash_evidence_confirmed_candidates?: number;
  };
  buyer_intelligence?: {
    configured_sources?: number;
    states?: string[];
    counties?: string[];
    ready?: boolean;
  };
};

// Scores are normalized acquisition-priority indexes (0-100), not literal percentages.
// External benchmark inputs are refreshed through the operating workflow; live buyer-network
// counts below come from the authenticated SAHJONY buyer directory at render time.
const markets: Market[] = [
  { metro: 'Pensacola', state: 'FL', tier: 'PRIORITY', score: 96, cashBuyer: 88, institutional: 70, wholesalerLiquidity: 94, affordability: 91, signal: 'Pinned SAHJONY Gulf Coast market. Lower basis, distress channels and proximity to Mobile create a two-market disposition corridor.', focus: 'Escambia County foreclosure, probate, tax delinquent, vacant, code-violation and absentee-owner SFR.', source: 'SAHJONY priority + 2026 investor-market benchmarks' },
  { metro: 'Memphis', state: 'TN', tier: 'HOT', score: 95, cashBuyer: 96, institutional: 97, wholesalerLiquidity: 96, affordability: 96, signal: 'One of the deepest investor-buyer markets nationally, with a large rental-buyer base and strong institutional participation.', focus: 'Rental-grade SFR, tired landlords, inherited property, tax delinquency and pre-foreclosure.', source: 'Realtor.com 2026 investor report + ATTOM Q1 2026' },
  { metro: 'Birmingham', state: 'AL', tier: 'HOT', score: 94, cashBuyer: 94, institutional: 90, wholesalerLiquidity: 95, affordability: 97, signal: 'High investor purchase share, low acquisition basis and strong landlord demand support fast disposition when rehab is controlled.', focus: 'Sub-$250K SFR, probate, tax delinquent, code violations and landlord fatigue.', source: 'Realtor.com 2026 investor report' },
  { metro: 'Mobile', state: 'AL', tier: 'HOT', score: 93, cashBuyer: 89, institutional: 100, wholesalerLiquidity: 91, affordability: 94, signal: 'ATTOM reported the highest institutional-buyer share among major metros in Q1 2026; pairs naturally with Pensacola sourcing.', focus: 'Affordable SFR, inherited property, tax delinquency, vacancy and code violations.', source: 'ATTOM Q1 2026' },
  { metro: 'Kansas City', state: 'MO', tier: 'HOT', score: 92, cashBuyer: 94, institutional: 88, wholesalerLiquidity: 94, affordability: 90, signal: 'Investor purchase share remains among the highest of the 50 largest metros, supporting rental and flip exits.', focus: 'Entry-level SFR, inherited homes, tired landlords and high-equity absentee owners.', source: 'Realtor.com 2026 investor report' },
  { metro: 'St. Louis', state: 'MO', tier: 'HOT', score: 92, cashBuyer: 94, institutional: 87, wholesalerLiquidity: 94, affordability: 93, signal: 'Very high investor share with broad affordable housing stock and repeat landlord demand.', focus: 'Value-add SFR, tax delinquency, probate, code violations and long-held equity.', source: 'Realtor.com 2026 investor report' },
  { metro: 'Houston', state: 'TX', tier: 'HOT', score: 91, cashBuyer: 96, institutional: 82, wholesalerLiquidity: 97, affordability: 85, signal: 'Exceptional investor transaction volume and cash participation; the opportunity is ZIP-specific and buyer-box driven.', focus: 'Harris County courthouse distress, foreclosure, tax, probate, code enforcement and absentee-owner SFR.', source: 'Houston investor market data 2026 + SAHJONY buyer intelligence' },
  { metro: 'Dallas-Fort Worth', state: 'TX', tier: 'HOT', score: 90, cashBuyer: 93, institutional: 85, wholesalerLiquidity: 97, affordability: 79, signal: 'Large transaction base, established investor ecosystem and continued institutional interest create deep disposition coverage.', focus: 'Entry-level and workforce SFR, tired landlords, probate, foreclosure and high-equity absentee owners.', source: 'Realtor.com 2026 investor report + CBRE 2026 investor intentions' },
  { metro: 'Cleveland', state: 'OH', tier: 'HOT', score: 90, cashBuyer: 95, institutional: 68, wholesalerLiquidity: 95, affordability: 98, signal: 'Low basis plus strong investor share creates attractive assignment economics for rehab and rental inventory.', focus: 'Value-add SFR, tax delinquent, code violations, inherited homes and long-held equity.', source: 'Realtor.com 2026 investor report' },
  { metro: 'Indianapolis', state: 'IN', tier: 'HOT', score: 89, cashBuyer: 91, institutional: 77, wholesalerLiquidity: 93, affordability: 91, signal: 'Large landlord and BRRRR ecosystem with one of the stronger investor purchase shares among major metros.', focus: 'Rental SFR, absentee owners, probate, tired landlords and moderate rehab.', source: 'Realtor.com 2026 investor report' },
  { metro: 'Oklahoma City', state: 'OK', tier: 'HOT', score: 88, cashBuyer: 90, institutional: 73, wholesalerLiquidity: 91, affordability: 94, signal: 'Affordable inventory and elevated investor share support repeat rental-buyer demand.', focus: 'Workforce SFR, inherited property, landlord fatigue, tax delinquency and deferred maintenance.', source: 'Realtor.com 2026 investor report' },
  { metro: 'San Antonio', state: 'TX', tier: 'HOT', score: 87, cashBuyer: 92, institutional: 78, wholesalerLiquidity: 92, affordability: 88, signal: 'Deep small-investor activity remains the core signal even as large institutional ownership faces tighter federal constraints.', focus: 'Entry-level SFR, military-area rentals, inherited homes, absentee owners and foreclosure distress.', source: 'Realtor.com 2026 investor report + Cotality reporting' },
  { metro: 'Jacksonville', state: 'FL', tier: 'HOT', score: 87, cashBuyer: 90, institutional: 82, wholesalerLiquidity: 94, affordability: 84, signal: 'Established rental-buyer ecosystem and institutional SFR footprint support disposition depth across Duval County.', focus: 'Duval County distress, rental-ready SFR, absentee owners, probate and light-to-medium rehab.', source: '2026 cash-buyer market research + institutional ownership studies' },
  { metro: 'Charlotte', state: 'NC', tier: 'HOT', score: 86, cashBuyer: 88, institutional: 84, wholesalerLiquidity: 94, affordability: 78, signal: 'Strong local investor ecosystem plus institutional demand and population growth support suburban SFR exits.', focus: 'Suburban SFR, tired landlords, inherited property and light-rehab inventory.', source: 'CBRE 2026 investor intentions + 2026 investor-market research' },
  { metro: 'Huntsville', state: 'AL', tier: 'HOT', score: 85, cashBuyer: 84, institutional: 91, wholesalerLiquidity: 87, affordability: 88, signal: 'Elevated institutional share and relatively attainable price points keep investor demand active.', focus: 'Sub-$300K SFR, absentee owners, probate, tired landlords and moderate rehab.', source: 'ATTOM Q1 2026' },
  { metro: 'Atlanta', state: 'GA', tier: 'HOT', score: 85, cashBuyer: 91, institutional: 86, wholesalerLiquidity: 97, affordability: 73, signal: 'Still one of the deepest U.S. disposition markets, but competition and acquisition basis require tighter deal selection.', focus: 'South and west metro distress, inherited property, tired landlords and deep-discount SFR.', source: 'CBRE 2026 investor intentions + 2026 cash-buyer research' },
  { metro: 'Las Vegas', state: 'NV', tier: 'WATCH', score: 82, cashBuyer: 91, institutional: 71, wholesalerLiquidity: 91, affordability: 68, signal: 'High investor share and cash usage support flips, but entry pricing makes spread discipline essential.', focus: 'Deep-equity distress, dated SFR, absentee owners and properties with clear renovation upside.', source: 'Realtor.com 2026 investor report + cash-buyer research' },
  { metro: 'Phoenix', state: 'AZ', tier: 'WATCH', score: 81, cashBuyer: 91, institutional: 72, wholesalerLiquidity: 92, affordability: 66, signal: 'Large investor ecosystem remains liquid, but higher acquisition basis compresses marginal wholesale deals.', focus: 'Only strong equity, meaningful price reductions, inherited property and value-add SFR.', source: '2026 cash-buyer and wholesale-market research' },
  { metro: 'Tampa', state: 'FL', tier: 'WATCH', score: 80, cashBuyer: 88, institutional: 77, wholesalerLiquidity: 92, affordability: 65, signal: 'Deep investor ownership base and cash demand remain attractive, but insurance and basis risk require wider spreads.', focus: 'Distressed SFR with meaningful equity, clean insurance diligence and verified rehab margin.', source: '2026 investor-market research' },
  { metro: 'Pittsburgh', state: 'PA', tier: 'WATCH', score: 79, cashBuyer: 84, institutional: 58, wholesalerLiquidity: 86, affordability: 92, signal: 'Affordable basis and expanding small-investor activity create selective value opportunities.', focus: 'Affordable SFR, inherited property, long-held equity and deferred maintenance.', source: 'Realtor.com 2026 investor research' },
  { metro: 'Boise City', state: 'ID', tier: 'WATCH', score: 75, cashBuyer: 72, institutional: 96, wholesalerLiquidity: 68, affordability: 55, signal: 'High institutional share is notable, but higher basis and thinner wholesale liquidity reduce assignment tolerance.', focus: 'Selective distress only; prioritize deep equity and buyer-confirmed demand before contracting.', source: 'ATTOM Q1 2026' },
];

function meter(value: number) { return `${Math.max(0, Math.min(100, value))}%`; }

export default function MarketIntelligencePage() {
  const [query, setQuery] = useState('');
  const [tier, setTier] = useState('ALL');
  const [buyers, setBuyers] = useState<BuyerDirectory | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetch('/api/backend/buyer-directory', { cache: 'no-store', headers: { Authorization: 'Bearer cookie-session' } })
      .then(async response => response.ok ? response.json() as Promise<BuyerDirectory> : null)
      .then(data => { if (!cancelled && data) setBuyers(data); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const visible = useMemo(() => markets
    .filter(market => tier === 'ALL' || market.tier === tier)
    .filter(market => `${market.metro} ${market.state}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => b.score - a.score), [query, tier]);

  const buyerSummary = buyers?.summary || {};
  const intelligence = buyers?.buyer_intelligence || {};

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY WHOLESALE OS · DAILY MARKET INTELLIGENCE</span>
        <h1>Nationwide search for markets where real cash buyers are actively buying.</h1>
        <p>Pensacola stays pinned. The national board ranks wholesaler disposition liquidity, cash-buyer demand, institutional / hedge-fund activity and affordability, then overlays SAHJONY&apos;s live verified buyer network.</p>
      </div>
      <div className={styles.heroCard}>
        <small>SEARCH MODE</small><strong>Nationwide</strong><span>Morning operating cycle · 8:00 AM CT</span>
      </div>
    </header>

    <section className={styles.kpis}>
      <article><span>Markets tracked</span><strong>{markets.length}</strong><small>National acquisition radar</small></article>
      <article><span>Pinned market</span><strong>Pensacola</strong><small>Escambia County, Florida</small></article>
      <article><span>SAHJONY buyers</span><strong>{buyerSummary.total_buyers ?? '—'}</strong><small>{buyerSummary.proof_of_funds_verified ?? 0} current POF verified</small></article>
      <article><span>Cash-buyer evidence</span><strong>{buyerSummary.cash_evidence_confirmed_candidates ?? '—'}</strong><small>{intelligence.configured_sources ?? 0} public deed sources configured</small></article>
    </section>

    <section className={styles.controls}>
      <label>Nationwide market search<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search city or state…" /></label>
      <div className={styles.tiers}>{['ALL', 'PRIORITY', 'HOT', 'WATCH'].map(value => <button key={value} className={tier === value ? styles.active : ''} onClick={() => setTier(value)}>{value}</button>)}</div>
    </section>

    <section className={styles.board}>
      {visible.map((market, index) => <article key={`${market.metro}-${market.state}`} className={market.tier === 'PRIORITY' ? styles.priority : ''}>
        <div className={styles.rank}><b>#{index + 1}</b><span className={styles[market.tier.toLowerCase()]}>{market.tier}</span></div>
        <div className={styles.title}><h2>{market.metro}, {market.state}</h2><strong>{market.score}<small>/100</small></strong></div>
        <p>{market.signal}</p>
        <div className={styles.metrics}>
          <div><span>Cash-buyer index</span><i><em style={{ width: meter(market.cashBuyer) }} /></i><b>{market.cashBuyer}</b></div>
          <div><span>Institutional / fund index</span><i><em style={{ width: meter(market.institutional) }} /></i><b>{market.institutional}</b></div>
          <div><span>Wholesale liquidity</span><i><em style={{ width: meter(market.wholesalerLiquidity) }} /></i><b>{market.wholesalerLiquidity}</b></div>
          <div><span>Affordability</span><i><em style={{ width: meter(market.affordability) }} /></i><b>{market.affordability}</b></div>
        </div>
        <div className={styles.focus}><span>ACQUISITION FOCUS</span><p>{market.focus}</p></div>
        <footer><span>{market.source}</span><a href={`/owner/deal-factory?state=${market.state}`}>Search deals →</a></footer>
      </article>)}
    </section>

    <section className={styles.method}>
      <div><span>RANKING LOGIC</span><h2>Cash buyers first. Hedge funds are a demand signal, not the strategy.</h2></div>
      <p>The score prioritizes active investor purchases, local disposition depth, attainable basis and distress-to-ARV spread. Institutional and fund activity increases the score where it adds real ZIP-level demand, but local and small investors remain the primary disposition engine.</p>
      <p>Live buyer counts come from SAHJONY&apos;s authenticated buyer directory and public-deed buyer intelligence. External market benchmarks are evidence inputs and should be refreshed as new ATTOM, Realtor.com, local deed and buyer-network data arrives.</p>
      <p className={styles.disclaimer}>Indexes are acquisition-priority signals, not literal cash-purchase percentages or guarantees of assignment liquidity. Every property still requires source-backed comps, title review, rehab validation and buyer-specific buy-box confirmation before contracting.</p>
    </section>
  </main>;
}

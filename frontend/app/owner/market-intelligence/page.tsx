'use client';

import { useMemo, useState } from 'react';
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

const markets: Market[] = [
  { metro: 'Pensacola', state: 'FL', tier: 'PRIORITY', score: 94, cashBuyer: 91, institutional: 70, wholesalerLiquidity: 92, affordability: 88, signal: 'Pinned SAHJONY market with strong investor economics and Gulf Coast distress channels.', focus: 'Escambia County foreclosure, probate, tax delinquent, vacant and absentee-owner SFR.', source: 'SAHJONY priority + national investor-market model' },
  { metro: 'Mobile', state: 'AL', tier: 'HOT', score: 93, cashBuyer: 88, institutional: 100, wholesalerLiquidity: 90, affordability: 91, signal: 'Highest reported institutional-buyer share among major Q1 2026 metros.', focus: 'Affordable SFR, inherited property, tax delinquency, code violations.', source: 'ATTOM Q1 2026' },
  { metro: 'Memphis', state: 'TN', tier: 'HOT', score: 92, cashBuyer: 91, institutional: 99, wholesalerLiquidity: 93, affordability: 95, signal: 'Deep rental-buyer base and very high institutional purchase share.', focus: 'Rental-grade 3/2 SFR, landlord fatigue, probate, pre-foreclosure.', source: 'ATTOM Q1 2026' },
  { metro: 'Huntsville', state: 'AL', tier: 'HOT', score: 89, cashBuyer: 84, institutional: 91, wholesalerLiquidity: 86, affordability: 86, signal: 'Institutional demand remains elevated with strong household growth economics.', focus: 'Sub-$300K SFR, absentee owners, probate and tired landlords.', source: 'ATTOM Q1 2026' },
  { metro: 'Cleveland', state: 'OH', tier: 'HOT', score: 88, cashBuyer: 95, institutional: 63, wholesalerLiquidity: 94, affordability: 97, signal: 'High all-cash participation and growing small-investor activity.', focus: 'Value-add SFR, tax delinquent, code violations, inherited homes.', source: 'Redfin + Realtor.com 2026' },
  { metro: 'Pittsburgh', state: 'PA', tier: 'HOT', score: 86, cashBuyer: 84, institutional: 55, wholesalerLiquidity: 87, affordability: 90, signal: 'Small-investor activity has expanded materially versus pre-pandemic levels.', focus: 'Affordable SFR, inherited properties, long-held equity.', source: 'Realtor.com 2026' },
  { metro: 'Jacksonville', state: 'FL', tier: 'HOT', score: 85, cashBuyer: 86, institutional: 79, wholesalerLiquidity: 90, affordability: 82, signal: 'Large existing institutional SFR footprint supports disposition depth.', focus: 'Duval County distress, rental-ready SFR, absentee owners.', source: 'GAO + institutional ownership research' },
  { metro: 'Charlotte', state: 'NC', tier: 'HOT', score: 84, cashBuyer: 82, institutional: 78, wholesalerLiquidity: 89, affordability: 77, signal: 'Large institutional SFR footprint plus deep local investor ecosystem.', focus: 'Suburban SFR, tired landlords, inherited and light-rehab inventory.', source: 'Institutional ownership research 2026' },
  { metro: 'Houston', state: 'TX', tier: 'HOT', score: 83, cashBuyer: 89, institutional: 68, wholesalerLiquidity: 91, affordability: 80, signal: 'Large cash-investor ecosystem; institutional activity is concentrated by ZIP rather than dominant metro-wide.', focus: 'Harris County courthouse distress, foreclosure, tax, probate and code enforcement.', source: 'Realtor.com + Houston market research 2026' },
  { metro: 'Tampa', state: 'FL', tier: 'WATCH', score: 79, cashBuyer: 84, institutional: 72, wholesalerLiquidity: 88, affordability: 68, signal: 'Deep investor ownership base, but higher acquisition basis requires stricter spread discipline.', focus: 'Distressed SFR with meaningful equity and verified rehab margin.', source: 'Institutional ownership research 2026' },
  { metro: 'Atlanta', state: 'GA', tier: 'WATCH', score: 76, cashBuyer: 82, institutional: 75, wholesalerLiquidity: 91, affordability: 70, signal: 'Still a major disposition market, but 2025 data showed investors becoming net sellers.', focus: 'Only pursue unusually strong discounts, high-equity distress and clean buyer coverage.', source: 'Realtor.com 2026' },
  { metro: 'Boise City', state: 'ID', tier: 'WATCH', score: 74, cashBuyer: 70, institutional: 96, wholesalerLiquidity: 67, affordability: 58, signal: 'High reported institutional share but higher basis can compress wholesale spreads.', focus: 'Selective distress only; prioritize deep equity and verified buyer demand.', source: 'ATTOM Q1 2026' },
];

function meter(value: number) { return `${Math.max(0, Math.min(100, value))}%`; }

export default function MarketIntelligencePage() {
  const [query, setQuery] = useState('');
  const [tier, setTier] = useState('ALL');

  const visible = useMemo(() => markets
    .filter(market => tier === 'ALL' || market.tier === tier)
    .filter(market => `${market.metro} ${market.state}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => b.score - a.score), [query, tier]);

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY WHOLESALE OS · DAILY MARKET INTELLIGENCE</span>
        <h1>Nationwide search for markets where real cash buyers are actively buying.</h1>
        <p>Pensacola stays pinned. The national board ranks wholesaler disposition liquidity, cash-buyer demand, institutional activity and affordability so acquisition effort follows buyer demand instead of guesswork.</p>
      </div>
      <div className={styles.heroCard}>
        <small>SEARCH MODE</small><strong>Nationwide</strong><span>Daily refresh target · 8:00 AM CT</span>
      </div>
    </header>

    <section className={styles.kpis}>
      <article><span>Markets tracked</span><strong>{markets.length}</strong><small>National acquisition radar</small></article>
      <article><span>Pinned market</span><strong>Pensacola</strong><small>Escambia County, Florida</small></article>
      <article><span>Top current signal</span><strong>Mobile</strong><small>Institutional buyer share leader</small></article>
      <article><span>Buyer model</span><strong>Cash-first</strong><small>Local + small investors weighted highest</small></article>
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
          <div><span>Cash buyers</span><i><em style={{ width: meter(market.cashBuyer) }} /></i><b>{market.cashBuyer}</b></div>
          <div><span>Institutional</span><i><em style={{ width: meter(market.institutional) }} /></i><b>{market.institutional}</b></div>
          <div><span>Wholesale liquidity</span><i><em style={{ width: meter(market.wholesalerLiquidity) }} /></i><b>{market.wholesalerLiquidity}</b></div>
          <div><span>Affordability</span><i><em style={{ width: meter(market.affordability) }} /></i><b>{market.affordability}</b></div>
        </div>
        <div className={styles.focus}><span>ACQUISITION FOCUS</span><p>{market.focus}</p></div>
        <footer><span>{market.source}</span><a href={`/owner/deal-factory?state=${market.state}`}>Search deals →</a></footer>
      </article>)}
    </section>

    <section className={styles.method}>
      <div><span>RANKING LOGIC</span><h2>Cash buyers first. Institutions are a signal, not the whole market.</h2></div>
      <p>The score prioritizes evidence of active cash/investor purchases, depth of local disposition demand, attainable price points and distress-to-ARV spread. Institutional activity is included because it can deepen buyer demand in selected ZIP codes, but small and local investors receive more weight because they represent most current investor purchases nationally.</p>
      <p className={styles.disclaimer}>Market scores are acquisition-priority signals, not guarantees of assignment liquidity. Every property still requires source-backed comps, title review, rehab validation and buyer-specific buy-box confirmation before contracting.</p>
    </section>
  </main>;
}

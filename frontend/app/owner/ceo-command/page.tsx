'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './v2.module.css';

const SIGN_IN = '/login?returnTo=/owner';

type KPI = {
  total_leads: number; hot_leads: number; active_deals: number; qualified_buyers: number;
  projected_assignment_revenue: number; probability_weighted_revenue: number;
  queued_tasks: number; failed_tasks: number; pending_approvals: number;
};
type Agent = { name: string; role: string; status: string; health: string; last_run_at?: string; last_status?: string; confidence?: number };
type CommandCenter = {
  generated_at: string; mode: string; kpis: KPI; agent_health: Agent[];
  approvals: Array<{ id: number; action_type: string; summary: string }>;
  deal_risk: Array<{ deal_id: number; stage: string; projected_assignment_fee: number; probability_to_close: number; next_action?: string }>;
};
type Lead = { id: number; seller_name: string; status: string; address?: string; city?: string; state?: string; mao?: number; distress_score?: number };
type Candidate = {
  lead_id: number; property_id: number; status: string;
  owner: { name?: string; verification_status?: string; confidence?: number };
  property: { address?: string; city?: string; state?: string; zip_code?: string; asking_price?: number; arv?: number; repairs?: number; distress_signals?: string[] };
  screening: { theoretical_buyer_price?: number; projected_assignment_spread?: number };
  source_count: number; next_action?: string;
};
type RealDeal = {
  deal_id: number; stage: string; owner: { name?: string; verified?: boolean };
  property: { address?: string; city?: string; state?: string; asking_price?: number; arv?: number; repairs?: number };
  underwriting: { target_contract_price?: number; target_buyer_price?: number; projected_assignment_fee?: number; probability_to_close?: number };
  next_action?: string;
};

const STAGES = ['new', 'contacting', 'qualified', 'offer_prepared', 'offer_sent', 'negotiating', 'under_contract', 'disposition', 'closing', 'closed'];

function money(value = 0) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0); }
function label(value = '') { return value.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase()); }
function err(error: unknown) { return error instanceof Error ? error.message : 'Data source unavailable'; }
function location(item: { city?: string; state?: string; address?: string }) { return [item.city, item.state].filter(Boolean).join(', ') || item.address || 'Location pending'; }
function canonicalClosePercentage(deal: { probability_to_close: number }) { return Math.round(deal.probability_to_close || 0); }

export default function CEOCommandCenter() {
  const [command, setCommand] = useState<CommandCenter | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [realDeals, setRealDeals] = useState<RealDeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);

  const request = useCallback(async (path: string) => {
    const response = await fetch(`/api/backend${path}`, { cache: 'no-store', headers: { Authorization: 'Bearer cookie-session' } });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace(SIGN_IN);
      throw new Error('Owner session required');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${path} failed (${response.status})`);
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setErrors([]);
    const results = await Promise.allSettled([
      request('/executive/command-center'),
      request('/crm/leads'),
      request('/wholesale/real-deal-candidates?min_assignment_fee=10000'),
      request('/wholesale/real-deals?property_type=single_family&owner_type=individual&min_assignment_fee=10000'),
    ]);
    const failures: string[] = [];
    if (results[0].status === 'fulfilled') setCommand(results[0].value); else failures.push(err(results[0].reason));
    if (results[1].status === 'fulfilled') setLeads(Array.isArray(results[1].value) ? results[1].value : []); else failures.push(err(results[1].reason));
    if (results[2].status === 'fulfilled') setCandidates(Array.isArray(results[2].value.candidates) ? results[2].value.candidates : []); else failures.push(err(results[2].reason));
    if (results[3].status === 'fulfilled') setRealDeals(Array.isArray(results[3].value.deals) ? results[3].value.deals : []); else failures.push(err(results[3].reason));
    setErrors(failures); setLoading(false);
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const output: Record<string, Lead[]> = Object.fromEntries(STAGES.map(stage => [stage, []]));
    for (const lead of leads) {
      const stage = String(lead.status || 'new').toLowerCase().replaceAll(' ', '_');
      (output[STAGES.includes(stage) ? stage : 'new'] ||= []).push(lead);
    }
    return output;
  }, [leads]);

  const kpi = command?.kpis;
  const verifiedSpread = realDeals.reduce((sum, deal) => sum + Number(deal.underwriting.projected_assignment_fee || 0), 0);
  const candidateSpread = candidates.reduce((sum, deal) => sum + Number(deal.screening.projected_assignment_spread || 0), 0);
  const healthyAgents = command?.agent_health?.filter(a => ['healthy', 'ok', 'online'].includes(String(a.health).toLowerCase())).length || 0;
  const totalAgents = command?.agent_health?.length || 0;
  const blockers = (kpi?.pending_approvals || 0) + (kpi?.failed_tasks || 0);
  const highestRiskDeal = command?.deal_risk?.[0];

  return <main className={styles.page}>
    <header className={styles.topbar}>
      <div>
        <span className={styles.eyebrow}>SAHJONY WHOLESALE OS</span>
        <h1>Command Center</h1>
        <p>Run the business from verified opportunity to assignment fee. AI prepares the work; you control consequential actions.</p>
      </div>
      <div className={styles.actions}>
        <a className={styles.secondary} href="/owner/real-deals">Open Real Deals</a>
        <button className={styles.primary} onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh OS'}</button>
      </div>
    </header>

    {errors.length > 0 && <section className={styles.error}><b>Some operating data is unavailable.</b>{errors.slice(0, 3).map(message => <span key={message}>{message}</span>)}</section>}

    <section className={styles.moneyStrip}>
      <article className={styles.moneyPrimary}><span>VERIFIED DEAL SPREAD</span><strong>{money(verifiedSpread)}</strong><small>{realDeals.length} promoted real deal{realDeals.length === 1 ? '' : 's'}</small></article>
      <article><span>SCREENING OPPORTUNITY</span><strong>{money(candidateSpread)}</strong><small>{candidates.length} verified candidate{candidates.length === 1 ? '' : 's'} awaiting promotion</small></article>
      <article><span>RISK-WEIGHTED REVENUE</span><strong>{money(kpi?.probability_weighted_revenue)}</strong><small>{highestRiskDeal ? `${canonicalClosePercentage(highestRiskDeal)}% close probability on lead risk item` : 'Current active pipeline forecast'}</small></article>
      <article className={blockers ? styles.needsAttention : ''}><span>NEEDS YOUR ATTENTION</span><strong>{blockers}</strong><small>{kpi?.pending_approvals || 0} approvals · {kpi?.failed_tasks || 0} failed tasks</small></article>
    </section>

    <section className={styles.operatingGrid}>
      <article className={`${styles.panel} ${styles.priorityPanel}`}>
        <div className={styles.panelHeader}><div><span>NEXT BEST ACTION</span><h2>What should happen now?</h2></div><a href="/owner/attention">Action Inbox →</a></div>
        <div className={styles.actionQueue}>
          {(command?.approvals || []).slice(0, 3).map(item => <a key={`approval-${item.id}`} href="/owner/attention"><i>!</i><span><b>{label(item.action_type)}</b><small>{item.summary}</small></span><em>Approve / reject</em></a>)}
          {candidates.slice(0, 3).map(item => <a key={`candidate-${item.property_id}`} href="/owner/real-deals"><i>$</i><span><b>{item.property.address}</b><small>{item.owner.name} · {money(item.screening.projected_assignment_spread)} screening spread</small></span><em>Verify + promote</em></a>)}
          {!command?.approvals?.length && !candidates.length && <div className={styles.clearState}><b>No urgent operator action.</b><span>The OS has no pending approvals or verified $10K+ candidates right now.</span></div>}
        </div>
      </article>

      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>REAL DEALS</span><h2>Money-ready opportunities</h2></div><a href="/owner/real-deals">View all →</a></div>
        <div className={styles.dealStack}>
          {realDeals.slice(0, 4).map(deal => <a href={`/owner/deals?deal=${deal.deal_id}`} key={deal.deal_id}>
            <div><b>{deal.property.address || `Deal #${deal.deal_id}`}</b><small>{deal.owner.name || 'Owner pending'} · {deal.property.city}, {deal.property.state}</small></div>
            <div className={styles.dealMoney}><strong>{money(deal.underwriting.projected_assignment_fee)}</strong><small>{label(deal.stage)}</small></div>
          </a>)}
          {!realDeals.length && <div className={styles.clearState}><b>No promoted real deals yet.</b><span>Verified candidates will appear here after manager promotion.</span></div>}
        </div>
      </article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}><div><span>OPERATING FLOW</span><h2>Discover → verify → contract → dispose → close</h2></div><a href="/owner/acquisition">Open prospects →</a></div>
      <div className={styles.flow}>
        <a href="/owner/acquisition"><span>01</span><b>Prospects</b><strong>{leads.length}</strong><small>Raw + contacted opportunities</small></a>
        <a href="/owner/lead-verification"><span>02</span><b>Verified Candidates</b><strong>{candidates.length}</strong><small>Individual owner + source evidence</small></a>
        <a href="/owner/real-deals"><span>03</span><b>Real Deals</b><strong>{realDeals.length}</strong><small>$10K+ verified spread</small></a>
        <a href="/owner/disposition"><span>04</span><b>Disposition</b><strong>{grouped.disposition?.length || 0}</strong><small>Buyer matching + offers</small></a>
        <a href="/owner/closing"><span>05</span><b>Closing</b><strong>{grouped.closing?.length || 0}</strong><small>Title + assignment + funding</small></a>
      </div>
    </section>

    <section className={styles.lowerGrid}>
      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>VERIFIED CANDIDATES</span><h2>Best screening opportunities</h2></div><a href="/owner/real-deals">Review candidates →</a></div>
        <div className={styles.candidateTable}>
          {candidates.slice(0, 6).map(item => <a key={item.property_id} href="/owner/real-deals">
            <span><b>{item.property.address}</b><small>{item.owner.name} · {location(item.property)}</small></span>
            <span><small>Ask</small><b>{money(item.property.asking_price)}</b></span>
            <span><small>ARV</small><b>{money(item.property.arv)}</b></span>
            <span><small>Spread</small><b className={styles.profit}>{money(item.screening.projected_assignment_spread)}</b></span>
          </a>)}
          {!candidates.length && <div className={styles.clearState}><b>No verified candidates pass the current gate.</b><span>Prospects need individual-owner evidence, economics, and at least $10K screening spread.</span></div>}
        </div>
      </article>

      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>AI WORKFORCE</span><h2>Automation health</h2></div><a href="/owner/jobs">Inspect agents →</a></div>
        <div className={styles.agentSummary}><strong>{healthyAgents}/{totalAgents || 0}</strong><span>agents healthy</span></div>
        <div className={styles.agentList}>
          {(command?.agent_health || []).slice(0, 5).map(agent => <div key={`${agent.name}-${agent.role}`}><i className={['healthy','ok','online'].includes(String(agent.health).toLowerCase()) ? styles.live : styles.warn}/><span><b>{agent.name}</b><small>{agent.last_status || agent.role || agent.status}</small></span></div>)}
          {!totalAgents && <div className={styles.clearState}><b>No agent telemetry.</b><span>Open AI Workforce for diagnostics.</span></div>}
        </div>
      </article>
    </section>
  </main>;
}

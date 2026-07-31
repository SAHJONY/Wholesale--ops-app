'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './v2.module.css';

const SESSION = 'sahjony_owner_session';
const SIGN_IN = '/login?returnTo=/owner';

type KPI = {
  total_leads: number;
  hot_leads: number;
  active_deals: number;
  qualified_buyers: number;
  projected_assignment_revenue: number;
  probability_weighted_revenue: number;
  queued_tasks: number;
  failed_tasks: number;
  pending_approvals: number;
};

type Agent = {
  name: string;
  role: string;
  status: string;
  health: string;
  last_run_at?: string;
  last_status?: string;
  confidence?: number;
};

type Lead = {
  id: number;
  seller_name: string;
  status: string;
  address?: string;
  city?: string;
  state?: string;
  mao?: number;
};

type CommandCenter = {
  generated_at: string;
  mode: string;
  kpis: KPI;
  agent_health: Agent[];
  approvals: Array<{ id: number; action_type: string; summary: string }>;
  deal_risk: Array<{ deal_id: number; stage: string; projected_assignment_fee: number; probability_to_close: number; next_action?: string }>;
};

const STAGES = ['new', 'qualified', 'contacted', 'negotiating', 'under_contract', 'title', 'buyer_found', 'closing', 'completed'];

function money(value = 0) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase());
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Unknown data-source failure';
}

export default function CEOCommandCenter() {
  const [command, setCommand] = useState<CommandCenter | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState<string[]>([]);

  const request = useCallback(async (path: string) => {
    const token = window.localStorage.getItem(SESSION) || '';
    if (!token) {
      window.location.replace(SIGN_IN);
      throw new Error('Owner session required');
    }
    const response = await fetch(`/api/backend${path}`, {
      cache: 'no-store',
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.localStorage.removeItem(SESSION);
      window.location.replace(SIGN_IN);
      throw new Error('Owner session expired');
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`;
      throw new Error(`${path}: ${detail}`);
    }
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setErrors([]);

    const [executiveResult, leadsResult] = await Promise.allSettled([
      request('/executive/command-center'),
      request('/crm/leads'),
    ]);

    const failures: string[] = [];

    if (executiveResult.status === 'fulfilled') {
      setCommand(executiveResult.value);
    } else {
      failures.push(errorMessage(executiveResult.reason));
    }

    if (leadsResult.status === 'fulfilled') {
      setLeads(Array.isArray(leadsResult.value) ? leadsResult.value : []);
    } else {
      failures.push(errorMessage(leadsResult.reason));
    }

    setErrors(failures);
    setLoading(false);
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const output: Record<string, Lead[]> = Object.fromEntries(STAGES.map(stage => [stage, []]));
    for (const lead of leads) {
      const normalized = String(lead.status || 'new').toLowerCase().replaceAll(' ', '_');
      const stage = STAGES.includes(normalized) ? normalized : 'new';
      output[stage].push(lead);
    }
    return output;
  }, [leads]);

  const kpi = command?.kpis;
  const healthyAgents = command?.agent_health?.filter(agent => ['healthy', 'ok', 'online'].includes(String(agent.health).toLowerCase())).length || 0;
  const totalAgents = command?.agent_health?.length || 0;

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY WHOLESALE OS · CEO CONTROL PLANE</span>
        <h1>Where is the money, what needs approval, and what is the AI workforce doing?</h1>
        <p>Nationwide wholesale operations with supervised autonomy and owner-controlled execution.</p>
      </div>
      <div className={styles.actions}>
        <button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh intelligence'}</button>
        <a href="/owner/attention">Review approvals</a>
      </div>
    </header>

    {errors.map(message => <div className={styles.error} key={message}>{message}</div>)}

    <section className={styles.kpis}>
      <article><span>Projected assignment fees</span><strong>{money(kpi?.projected_assignment_revenue)}</strong><small>{command ? 'Current active pipeline' : 'Executive source unavailable'}</small></article>
      <article><span>Probability-weighted revenue</span><strong>{money(kpi?.probability_weighted_revenue)}</strong><small>{command ? 'Risk-adjusted forecast' : 'Executive source unavailable'}</small></article>
      <article><span>Deals under management</span><strong>{kpi?.active_deals || 0}</strong><small>{command?.deal_risk?.length || 0} risk-scored</small></article>
      <article><span>Owner approvals</span><strong>{kpi?.pending_approvals || 0}</strong><small>External actions remain blocked</small></article>
      <article><span>AI workforce</span><strong>{healthyAgents}/{totalAgents}</strong><small>Agents healthy</small></article>
      <article><span>Priority leads</span><strong>{kpi?.hot_leads || 0}</strong><small>{leads.length} leads loaded</small></article>
    </section>

    <section className={styles.twoColumn}>
      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>AI WORKFORCE</span><h2>Agent operations</h2></div><a href="/owner/jobs">Open automation</a></div>
        <div className={styles.agentGrid}>
          {(command?.agent_health || []).map(agent => <div className={styles.agent} key={`${agent.name}-${agent.role}`}>
            <div><i className={String(agent.health).toLowerCase() === 'healthy' ? styles.live : styles.warn}/><b>{agent.name}</b></div>
            <span>{agent.role}</span>
            <p>{agent.last_status || agent.status || 'Waiting for work'}</p>
            <small>Confidence {Math.round((agent.confidence || 0) * 100)}% · Last run {agent.last_run_at ? new Date(agent.last_run_at).toLocaleString() : 'Not yet'}</small>
          </div>)}
          {!totalAgents && <p className={styles.empty}>{command ? 'No agent telemetry reported yet.' : 'Executive intelligence source unavailable.'}</p>}
        </div>
      </article>

      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>REVENUE CONTROL</span><h2>Deal forecast</h2></div><a href="/owner/deals">Open deals</a></div>
        <div className={styles.dealList}>
          {(command?.deal_risk || []).slice(0, 8).map(deal => <div key={deal.deal_id}>
            <span><b>Deal #{deal.deal_id} · {label(deal.stage)}</b><small>{deal.next_action || 'Review next milestone'}</small></span>
            <span><b>{money(deal.projected_assignment_fee)}</b><small>{Math.round((deal.probability_to_close || 0) * 100)}% close probability</small></span>
          </div>)}
          {!command?.deal_risk?.length && <p className={styles.empty}>{command ? 'No active deal forecast yet.' : 'Executive intelligence source unavailable.'}</p>}
        </div>
      </article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}><div><span>ACQUISITION PIPELINE</span><h2>Lead-to-close operating board</h2></div><a href="/owner/acquisition">Open acquisitions</a></div>
      <div className={styles.board}>
        {STAGES.map(stage => <section key={stage}>
          <header><span>{label(stage)}</span><strong>{grouped[stage]?.length || 0}</strong></header>
          <div>
            {(grouped[stage] || []).slice(0, 5).map(lead => <a href={`/owner/acquisition?lead=${lead.id}`} key={lead.id}>
              <b>{lead.seller_name || `Lead #${lead.id}`}</b>
              <small>{[lead.city, lead.state].filter(Boolean).join(', ') || lead.address || 'Location pending'}</small>
              <span>{lead.mao ? `MAO ${money(lead.mao)}` : 'Valuation pending'}</span>
            </a>)}
            {!grouped[stage]?.length && <p>Empty</p>}
          </div>
        </section>)}
      </div>
    </section>
  </main>;
}

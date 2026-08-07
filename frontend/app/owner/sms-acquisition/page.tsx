'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './sms.module.css';

const API_URL = '/api/backend';
const SIGN_IN = '/login?returnTo=/owner/sms-acquisition';

type Lead = {
  id: number;
  seller_name: string;
  phone?: string;
  status: string;
  motivation_score?: number;
  distress_score?: number;
  timeline_days?: number;
  property?: {
    address?: string;
    city?: string;
    state?: string;
    zip_code?: string;
    asking_price?: number;
    arv?: number;
    repairs?: number;
    mao?: number;
  };
};

type Outbound = {
  id: number;
  lead_id: number;
  channel: string;
  provider: string;
  status: string;
  provider_status?: string;
  created_at: string;
};

type Approval = {
  id: number;
  entity_type: string;
  entity_id: number;
  action_type: string;
  summary: string;
};

type Snapshot = { leads?: Lead[] };
type CommandCenter = { approvals?: Approval[] };

type WorkflowStep = {
  title: string;
  subtitle: string;
  state: 'live' | 'guarded' | 'planned';
};

const workflow: WorkflowStep[] = [
  { title: 'Lead enters', subtitle: 'Distress / off-market intake', state: 'live' },
  { title: 'Compliance gate', subtitle: 'DNC + consent + channel authorization', state: 'guarded' },
  { title: 'SMS outreach', subtitle: 'Bland Messaging outbound request', state: 'guarded' },
  { title: 'Seller replies', subtitle: 'Signed Bland webhook + STOP interception', state: 'live' },
  { title: 'AI qualification', subtitle: 'Dual-model motivation · condition · timeline · price', state: 'live' },
  { title: 'Hot-lead routing', subtitle: 'Autonomous acquisitions handoff task', state: 'live' },
  { title: 'Underwriting', subtitle: 'ARV · repairs · MAO · assignment range', state: 'live' },
  { title: 'Follow-up', subtitle: 'Behavior-based nurture and exact callbacks', state: 'planned' },
];

function money(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

function scoreLead(lead: Lead) {
  const motivation = Number(lead.motivation_score || 0);
  const distress = Number(lead.distress_score || 0);
  const timeline = lead.timeline_days && lead.timeline_days <= 30 ? 15 : lead.timeline_days && lead.timeline_days <= 60 ? 8 : 0;
  return Math.max(0, Math.min(100, Math.round(motivation * 0.5 + distress * 0.35 + timeline)));
}

function qualification(score: number) {
  if (score >= 70) return 'HOT';
  if (score >= 45) return 'WARM';
  return 'NURTURE';
}

function requestError(error: unknown) {
  return error instanceof Error ? error.message : 'Unable to load SMS acquisition data';
}

export default function SmsAcquisitionWorkspace() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [outbound, setOutbound] = useState<Outbound[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');

  const request = useCallback(async (path: string) => {
    const response = await fetch(`${API_URL}${path}`, {
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Authorization: 'Bearer cookie-session' },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace(SIGN_IN);
      throw new Error('Owner session required');
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`;
      throw new Error(`${path}: ${detail}`);
    }
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [snapshotResult, outboundResult, commandResult] = await Promise.allSettled([
        request('/activation/snapshot'),
        request('/outbound/requests'),
        request('/executive/command-center'),
      ]);

      if (snapshotResult.status === 'fulfilled') {
        const snapshot = snapshotResult.value as Snapshot;
        setLeads(Array.isArray(snapshot.leads) ? snapshot.leads : []);
      }
      if (outboundResult.status === 'fulfilled') {
        setOutbound(Array.isArray(outboundResult.value) ? outboundResult.value : []);
      }
      if (commandResult.status === 'fulfilled') {
        const command = commandResult.value as CommandCenter;
        setApprovals((command.approvals || []).filter(item => item.entity_type === 'outbound_request'));
      }

      const failures = [snapshotResult, outboundResult, commandResult]
        .filter(result => result.status === 'rejected')
        .map(result => result.status === 'rejected' ? requestError(result.reason) : '');
      if (failures.length) setError(failures.join(' · '));
    } catch (err) {
      setError(requestError(err));
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const ranked = useMemo(() => leads
    .map(lead => ({ ...lead, aiScore: scoreLead(lead) }))
    .sort((a, b) => b.aiScore - a.aiScore), [leads]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return ranked;
    return ranked.filter(lead => [
      lead.seller_name,
      lead.phone,
      lead.status,
      lead.property?.address,
      lead.property?.city,
      lead.property?.state,
      lead.property?.zip_code,
    ].filter(Boolean).join(' ').toLowerCase().includes(needle));
  }, [query, ranked]);

  const sms = outbound.filter(item => item.channel === 'sms' && item.provider === 'bland');
  const delivered = sms.filter(item => ['delivered', 'sent', 'accepted', 'queued'].includes(String(item.provider_status || item.status).toLowerCase())).length;
  const hot = ranked.filter(item => item.aiScore >= 70).length;
  const pending = approvals.length;

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY WHOLESALE OS · BLAND AI SELLER ACQUISITION</span>
        <h1>Agentic SMS Wholesale Acquisition</h1>
        <p>Bland Messaging handles SMS and voice while SAHJONY agents classify, qualify, score, route, and prepare the next action behind deterministic compliance and owner approval.</p>
      </div>
      <div className={styles.heroActions}>
        <button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
        <a href="/owner/communications">Open Bland communications</a>
      </div>
    </header>

    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Seller leads</span><strong>{leads.length}</strong><small>Current acquisition workspace</small></article>
      <article><span>Hot opportunities</span><strong>{hot}</strong><small>Score 70+</small></article>
      <article><span>Bland SMS requests</span><strong>{sms.length}</strong><small>{delivered} queued / accepted / sent / delivered</small></article>
      <article><span>Owner approvals</span><strong>{pending}</strong><small>External messaging remains gated</small></article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div><span>WORKFLOW</span><h2>Autonomous seller acquisition engine</h2></div>
        <div className={styles.legend}><i className={styles.liveDot}/>Live <i className={styles.guardDot}/>Approval-gated <i className={styles.planDot}/>Next phase</div>
      </div>
      <div className={styles.workflow}>
        {workflow.map((step, index) => <div className={styles.workflowItem} key={step.title}>
          <article className={`${styles.node} ${styles[step.state]}`}>
            <small>STEP {index + 1}</small>
            <strong>{step.title}</strong>
            <span>{step.subtitle}</span>
          </article>
          {index < workflow.length - 1 && <i className={styles.connector}>→</i>}
        </div>)}
      </div>
      <div className={styles.guardrail}>
        <b>Hard guardrail:</b> STOP / opt-out, DNC, missing consent, expired authorization, quiet-hours failures, or owner rejection terminate outbound execution. Bland is the transport; the AI layer cannot override compliance.
      </div>
    </section>

    <section className={styles.twoCol}>
      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>AI QUALIFICATION</span><h2>Conversation memory</h2></div></div>
        <div className={styles.qualGrid}>
          {['Owner confirmed', 'Seller intent', 'Motivation', 'Occupancy', 'Property condition', 'Major repairs', 'Selling timeline', 'Asking price', 'Mortgage / liens', 'Decision makers', 'Best callback time', 'Appointment intent'].map(item => <div key={item}><i/> {item}</div>)}
        </div>
        <p className={styles.muted}>Claude is primary, OpenAI is the operational fallback, and deterministic routing remains available when neither model can answer. Seller-stated facts stay separate from verified property facts.</p>
      </article>

      <article className={styles.panel}>
        <div className={styles.panelHeader}><div><span>AGENTIC ROUTING</span><h2>Behavior-based decisions</h2></div></div>
        <div className={styles.rules}>
          <div><b>Seller replies</b><span>Bland webhook → classify → persistent AI qualification</span></div>
          <div><b>STOP / unsubscribe</b><span>Immediate suppression + consent revocation</span></div>
          <div><b>Call me</b><span>HOT classification → acquisitions handoff task</span></div>
          <div><b>Negotiating</b><span>Preserve asking price and seller evidence → next-action draft</span></div>
          <div><b>Ambiguous / risky</b><span>Human-review route instead of autonomous reply</span></div>
          <div><b>HOT score</b><span>Priority task → underwriting and acquisitions workflow</span></div>
        </div>
      </article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div><span>SELLER QUEUE</span><h2>Acquisition priority</h2></div>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search seller, city, ZIP, status…" />
      </div>
      <div className={styles.tableWrap}>
        <table>
          <thead><tr><th>Seller</th><th>Property</th><th>Status</th><th>AI score</th><th>Class</th><th>ARV</th><th>Repairs</th><th>MAO</th><th>Action</th></tr></thead>
          <tbody>
            {visible.slice(0, 50).map(lead => <tr key={lead.id}>
              <td><b>{lead.seller_name || `Lead #${lead.id}`}</b><small>{lead.phone || 'Phone unavailable'}</small></td>
              <td><b>{[lead.property?.city, lead.property?.state].filter(Boolean).join(', ') || 'Location pending'}</b><small>{lead.property?.address || lead.property?.zip_code || 'Property pending'}</small></td>
              <td>{lead.status || 'new'}</td>
              <td><strong>{lead.aiScore}</strong></td>
              <td><span className={`${styles.badge} ${lead.aiScore >= 70 ? styles.hot : lead.aiScore >= 45 ? styles.warm : styles.nurture}`}>{qualification(lead.aiScore)}</span></td>
              <td>{money(lead.property?.arv)}</td>
              <td>{money(lead.property?.repairs)}</td>
              <td>{money(lead.property?.mao)}</td>
              <td><a className={styles.rowAction} href="/owner/communications">Start Bland SMS</a></td>
            </tr>)}
            {!visible.length && <tr><td colSpan={9} className={styles.empty}>No seller leads match the current filter.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    <section className={styles.readiness}>
      <article><span>LIVE</span><b>Bland outbound transport</b><p>SMS uses Bland /v1/sms/send; voice remains on Bland calls. No SAHJONY Twilio account is required.</p></article>
      <article><span>LIVE</span><b>Signed inbound ingestion</b><p>Bland HMAC webhooks route seller-authored messages into STOP handling and the agentic SMS brain.</p></article>
      <article><span>LIVE</span><b>Agentic reply brain</b><p>Intent classification, structured qualification, HOT routing, conversation memory, and draft generation.</p></article>
      <article><span>NEXT</span><b>Autonomous scheduling</b><p>Calendar-aware appointment scheduling and exact follow-up execution remain the next controlled integration.</p></article>
    </section>
  </main>;
}

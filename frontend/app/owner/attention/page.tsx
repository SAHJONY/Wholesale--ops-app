'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = '/api/backend';
const SESSION_STORAGE = 'sahjony_owner_session';

type Item = Record<string, any>;
type Summary = {
  generated_at: string;
  status: string;
  attention_score: number;
  counts: Record<string, number>;
  overdue_followups: Item[];
  due_soon_followups: Item[];
  failed_tasks: Item[];
  pending_approvals: Item[];
  high_risk_deals: Item[];
  recent_activity: Item[];
};

function date(value?: string) {
  return value ? new Date(value).toLocaleString() : '—';
}

function money(value?: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);
}

export default function OwnerAttentionCenter() {
  const [token, setToken] = useState('');
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (tokenOverride?: string) => {
    const activeToken = tokenOverride || token;
    if (!activeToken) return;
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_URL}/owner-insights/summary`, {
        cache: 'no-store',
        headers: { Authorization: `Bearer ${activeToken}` },
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {

        setToken('');
        throw new Error('Owner session expired. Sign in again.');
      }
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load attention center');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    const stored = 'cookie-session';
    setToken(stored);
    if (stored) void load(stored);
  }, [load]);

  if (!token) return <main className={styles.setup}><section className={styles.setupCard}><h1>Owner session required</h1><p>{error || 'Sign in to review operational attention items.'}</p><a className={styles.linkButton} href="/owner">Go to owner sign in</a></section></main>;

  const counts = summary?.counts || {};
  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>OWNER ATTENTION CENTER</span><h1>What needs action now</h1><p>Overdue work, failed automation, approvals, risk, and recent operating activity.</p></div>
      <div className={styles.actions}><button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button><a className={styles.linkButton} href="/owner/operations">Scheduled Operations</a><a className={styles.linkButton} href="/owner/activate">Activation Console</a><a className={styles.linkButton} href="/owner">Control Plane</a></div>
    </header>
    {error && <div className={styles.error}>{error}</div>}
    <section className={styles.metrics}>
      <article><span>Operational status</span><strong>{summary?.status || '—'}</strong></article>
      <article><span>Attention score</span><strong>{summary?.attention_score ?? 0}</strong></article>
      <article><span>Overdue follow-ups</span><strong>{counts.overdue_followups || 0}</strong></article>
      <article><span>Failed tasks</span><strong>{counts.failed_tasks || 0}</strong></article>
      <article><span>Pending approvals</span><strong>{counts.pending_approvals || 0}</strong></article>
      <article><span>High-risk deals</span><strong>{counts.high_risk_deals || 0}</strong></article>
      <article><span>Due in 24 hours</span><strong>{counts.due_soon_followups || 0}</strong></article>
      <article><span>Queued tasks</span><strong>{counts.queued_tasks || 0}</strong></article>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>OVERDUE</span><h2>Follow-ups requiring action</h2></div></div><div className={styles.list}>{summary?.overdue_followups.length ? summary.overdue_followups.map(item => <div key={item.id}><span><b>{item.title}</b><small>Priority {item.priority} · Due {date(item.due_at)}</small><small>Lead {item.lead_id || '—'} · Deal {item.deal_id || '—'}</small></span></div>) : <p>No overdue follow-ups.</p>}</div></article>
      <article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>AUTOMATION</span><h2>Failed tasks</h2></div></div><div className={styles.list}>{summary?.failed_tasks.length ? summary.failed_tasks.map(item => <div key={item.id}><span><b>{item.task_type.replaceAll('_', ' ')}</b><small>{item.error || 'Unknown error'}</small><small>{date(item.updated_at)}</small></span><span className={styles.risk}>P{item.priority}</span></div>) : <p>No failed autonomous tasks.</p>}</div></article>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>CONTROL GATE</span><h2>Pending approvals</h2></div></div><div className={styles.list}>{summary?.pending_approvals.length ? summary.pending_approvals.map(item => <div key={item.id}><span><b>{item.action_type.replaceAll('_', ' ')}</b><small>{item.summary}</small><small>{date(item.created_at)}</small></span></div>) : <p>No approvals waiting.</p>}</div></article>
      <article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>DEAL RISK</span><h2>High-risk deals</h2></div></div><div className={styles.list}>{summary?.high_risk_deals.length ? summary.high_risk_deals.map(item => <div key={item.id}><span><b>Deal #{item.id} · {item.property.city || 'Unknown'}, {item.property.state || ''}</b><small>{item.stage} · {item.probability_to_close || 0}% close probability · {money(item.projected_assignment_fee)}</small><small>{item.next_action || 'Review deal strategy'}</small></span><span className={styles.risk}>Risk {Math.round(item.risk_score || 0)}</span></div>) : <p>No high-risk active deals.</p>}</div></article>
    </section>

    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>AUDIT TRAIL</span><h2>Recent operating activity</h2></div><small>Updated {date(summary?.generated_at)}</small></div><div className={styles.list}>{summary?.recent_activity.length ? summary.recent_activity.map(item => <div key={item.id}><span><b>{item.type.replaceAll('_', ' ')}</b><small>{item.summary}</small><small>{date(item.created_at)}</small></span></div>) : <p>No activity recorded yet.</p>}</div></section>
  </main>;
}

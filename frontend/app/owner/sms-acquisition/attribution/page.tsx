'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../campaigns/campaigns.module.css';

const API_URL = '/api/backend';
const SIGN_IN = '/login?returnTo=/owner/sms-acquisition/attribution';

type CampaignRow = {
  campaign_id: number;
  campaign_name: string;
  status: string;
  audience: number;
  sent: number;
  replied: number;
  qualified: number;
  appointments_booked: number;
  offers_created: number;
  offers_accepted: number;
  contracts_signed: number;
  assignments_closed: number;
  assignment_revenue: number;
  revenue_per_sent: number;
  revenue_per_closed: number;
};

type Summary = { campaigns?: CampaignRow[]; campaign_count?: number };

function money(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);
}

function pct(n: number, d: number) {
  return d > 0 ? `${((n / d) * 100).toFixed(1)}%` : '0.0%';
}

export default function AttributionDashboard() {
  const [rows, setRows] = useState<CampaignRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await fetch(`${API_URL}/sms-attribution/summary`, {
        cache: 'no-store', credentials: 'same-origin', headers: { Authorization: 'Bearer cookie-session' },
      });
      const data = await response.json().catch(() => ({})) as Summary & { detail?: string };
      if (response.status === 401 || response.status === 403) {
        window.location.replace(SIGN_IN); return;
      }
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      setRows(Array.isArray(data.campaigns) ? data.campaigns : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load acquisition attribution');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const totals = useMemo(() => rows.reduce((acc, row) => ({
    sent: acc.sent + row.sent,
    replied: acc.replied + row.replied,
    appointments: acc.appointments + row.appointments_booked,
    contracts: acc.contracts + row.contracts_signed,
    closed: acc.closed + row.assignments_closed,
    revenue: acc.revenue + row.assignment_revenue,
  }), { sent: 0, replied: 0, appointments: 0, contracts: 0, closed: 0, revenue: 0 }), [rows]);

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY AI ACQUISITION</span>
        <h1>Revenue Attribution</h1>
        <p>Measure the complete seller-acquisition funnel from campaign delivery through replies, qualification, appointments, offers, signed contracts, closed assignments and realized assignment revenue.</p>
      </div>
      <nav>
        <a href="/owner/sms-acquisition">AI SMS Acquisition</a>
        <a href="/owner/sms-acquisition/campaigns">Campaign Manager</a>
        <a href="/owner/sms-acquisition/scheduling">Scheduling</a>
        <button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
      </nav>
    </header>

    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>SMS sent</span><strong>{totals.sent}</strong><small>{pct(totals.replied, totals.sent)} reply rate</small></article>
      <article><span>Appointments</span><strong>{totals.appointments}</strong><small>{pct(totals.appointments, totals.replied)} of replies</small></article>
      <article><span>Contracts</span><strong>{totals.contracts}</strong><small>{pct(totals.contracts, totals.sent)} of sends</small></article>
      <article><span>Assignment revenue</span><strong>{money(totals.revenue)}</strong><small>{money(totals.sent ? totals.revenue / totals.sent : 0)} per SMS sent</small></article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}><div><span className={styles.eyebrow}>FUNNEL</span><h2>Campaign economics</h2></div><small>{rows.length} campaigns</small></div>
      <div className={styles.tableWrap}><table>
        <thead><tr><th>Campaign</th><th>Sent</th><th>Replies</th><th>Qualified</th><th>Appointments</th><th>Offers</th><th>Contracts</th><th>Closed</th><th>Revenue</th><th>Revenue / send</th></tr></thead>
        <tbody>
          {rows.map(row => <tr key={row.campaign_id}>
            <td><b>{row.campaign_name}</b><small>{row.status} · #{row.campaign_id}</small></td>
            <td>{row.sent}<small>{pct(row.sent, row.audience)} of audience</small></td>
            <td>{row.replied}<small>{pct(row.replied, row.sent)}</small></td>
            <td>{row.qualified}</td>
            <td>{row.appointments_booked}</td>
            <td>{row.offers_created}<small>{row.offers_accepted} accepted</small></td>
            <td>{row.contracts_signed}</td>
            <td>{row.assignments_closed}</td>
            <td><b>{money(row.assignment_revenue)}</b></td>
            <td>{money(row.revenue_per_sent)}</td>
          </tr>)}
          {!rows.length && <tr><td colSpan={10} className={styles.empty}>No attributed campaign activity yet.</td></tr>}
        </tbody>
      </table></div>
    </section>

    <section className={styles.panel}>
      <div className={styles.guardrail}><b>Attribution rule</b><br/>Revenue is counted only from explicit assignment-close or assignment-fee events tied to a lead and, when available, its originating SAHJONY campaign. Seller replies, qualification and booked appointments are derived from system-of-record conversation and scheduling data.</div>
    </section>
  </main>;
}

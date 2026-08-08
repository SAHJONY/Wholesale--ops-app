'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../campaigns/campaigns.module.css';

const API_URL = '/api/backend';
const SIGN_IN = '/login?returnTo=/owner/sms-acquisition/scheduling';

type Appointment = {
  id: number;
  lead_id: number;
  status: string;
  requested_start_at?: string;
  recipient_timezone?: string;
  duration_minutes: number;
  raw_preference?: string;
  confidence: number;
  provider?: string;
  calendar_event_id?: string;
};

type FollowUp = {
  id: number;
  lead_id: number;
  due_at: string;
  recipient_timezone?: string;
  reason: string;
  body_draft?: string;
  status: string;
  cancellation_reason?: string;
  outbound_request_id?: number;
};

type Summary = Record<string, number>;

export default function SchedulingCommandCenter() {
  const [summary, setSummary] = useState<Summary>({});
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [followups, setFollowups] = useState<FollowUp[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const request = useCallback(async (path: string, options: RequestInit = {}) => {
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer cookie-session',
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace(SIGN_IN);
      throw new Error('Owner session required');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [summaryData, appointmentsData, followupsData] = await Promise.all([
        request('/sms-scheduling/summary'),
        request('/sms-scheduling/appointments'),
        request('/sms-scheduling/follow-ups'),
      ]);
      setSummary(summaryData || {});
      setAppointments(Array.isArray(appointmentsData) ? appointmentsData : []);
      setFollowups(Array.isArray(followupsData) ? followupsData : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load scheduling');
    } finally { setLoading(false); }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  async function syncConversations() {
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request('/sms-scheduling/sync-conversations', { method: 'POST', body: JSON.stringify({ limit: 100 }) });
      setNotice(`Synced ${result.synced} seller conversations into appointment/follow-up orchestration. No messages or calendar events were created.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to sync conversations'); }
    finally { setLoading(false); }
  }

  async function prepareDue() {
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request('/sms-scheduling/follow-ups/prepare-due', { method: 'POST', body: JSON.stringify({ limit: 25 }) });
      setNotice(`${result.pending_owner_approval} due follow-ups prepared for owner approval; ${result.blocked} blocked; ${result.needs_timezone} need timezone resolution. No SMS was sent.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to prepare due follow-ups'); }
    finally { setLoading(false); }
  }

  const ready = useMemo(() => appointments.filter(item => item.status === 'ready_to_book').length, [appointments]);
  const confirmation = useMemo(() => appointments.filter(item => item.status === 'needs_confirmation').length, [appointments]);
  const due = useMemo(() => followups.filter(item => item.status === 'scheduled' && new Date(item.due_at).getTime() <= Date.now()).length, [followups]);
  const pendingApproval = useMemo(() => followups.filter(item => item.status === 'pending_owner_approval').length, [followups]);

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY AI ACQUISITION</span>
        <h1>Scheduling Command Center</h1>
        <p>Convert seller replies into callback and appointment work, cancel stale nurture when sellers re-engage, and prepare due follow-ups through the same compliance and owner-approval controls used by Bland messaging.</p>
      </div>
      <nav>
        <a href="/owner/sms-acquisition">AI SMS Acquisition</a>
        <a href="/owner/sms-acquisition/campaigns">Campaign Manager</a>
        <button onClick={() => void syncConversations()} disabled={loading}>Sync conversations</button>
        <button onClick={() => void prepareDue()} disabled={loading}>Prepare due follow-ups</button>
      </nav>
    </header>

    {notice && <div className={styles.notice}>{notice}</div>}
    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Ready to book</span><strong>{ready}</strong><small>Explicit seller date/time resolved</small></article>
      <article><span>Needs confirmation</span><strong>{confirmation}</strong><small>Ambiguous callback intent fails closed</small></article>
      <article><span>Due follow-ups</span><strong>{due}</strong><small>Waiting for compliance preparation</small></article>
      <article><span>Pending owner approval</span><strong>{pendingApproval}</strong><small>No automatic send authority</small></article>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}><div><span className={styles.eyebrow}>APPOINTMENTS</span><h2>Seller callback & appointment queue</h2></div><small>{appointments.length} records</small></div>
      <div className={styles.tableWrap}><table>
        <thead><tr><th>Lead</th><th>Status</th><th>Requested time</th><th>Timezone</th><th>Confidence</th><th>Seller wording</th><th>Calendar</th></tr></thead>
        <tbody>
          {appointments.map(item => <tr key={item.id}>
            <td><b>Lead #{item.lead_id}</b><small>Appointment #{item.id}</small></td>
            <td><span className={styles.badge}>{item.status}</span></td>
            <td>{item.requested_start_at ? new Date(item.requested_start_at).toLocaleString() : 'Needs confirmation'}</td>
            <td>{item.recipient_timezone || 'Unresolved'}</td>
            <td>{item.confidence}%</td>
            <td>{item.raw_preference || 'No explicit wording captured'}</td>
            <td>{item.calendar_event_id ? `${item.provider || 'calendar'} · ${item.calendar_event_id}` : 'Not booked'}</td>
          </tr>)}
          {!appointments.length && <tr><td colSpan={7} className={styles.empty}>No appointment requests yet.</td></tr>}
        </tbody>
      </table></div>
    </section>

    <section className={styles.panel}>
      <div className={styles.panelHeader}><div><span className={styles.eyebrow}>FOLLOW-UP</span><h2>Behavior-based nurture queue</h2></div><small>{followups.length} jobs</small></div>
      <div className={styles.tableWrap}><table>
        <thead><tr><th>Lead</th><th>Status</th><th>Due</th><th>Timezone</th><th>Reason</th><th>Draft</th><th>Outbound request</th></tr></thead>
        <tbody>
          {followups.map(item => <tr key={item.id}>
            <td><b>Lead #{item.lead_id}</b><small>Follow-up #{item.id}</small></td>
            <td><span className={styles.badge}>{item.status}</span></td>
            <td>{new Date(item.due_at).toLocaleString()}</td>
            <td>{item.recipient_timezone || 'Needs timezone'}</td>
            <td>{item.reason}</td>
            <td>{item.body_draft || item.cancellation_reason || '—'}</td>
            <td>{item.outbound_request_id ? `#${item.outbound_request_id}` : 'Not prepared'}</td>
          </tr>)}
          {!followups.length && <tr><td colSpan={7} className={styles.empty}>No active follow-up jobs yet.</td></tr>}
        </tbody>
      </table></div>
    </section>

    <section className={styles.panel}>
      <div className={styles.guardrail}><b>Execution boundary</b><br/>Explicit seller times may become ready-to-book records. Ambiguous wording requires confirmation. Follow-up jobs never send by themselves: due jobs are rechecked for DNC, consent, suppression and quiet hours, then converted into an owner-approved Bland outbound request.</div>
      <small>{Object.entries(summary).map(([key, value]) => `${key}: ${value}`).join(' · ') || 'No scheduling state yet.'}</small>
    </section>
  </main>;
}

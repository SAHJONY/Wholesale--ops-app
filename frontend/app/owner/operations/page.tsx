'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = 'https://backend-pi-opal-65.vercel.app';
const SESSION_STORAGE = 'sahjony_owner_session';

type Cycle = {
  id: number;
  summary: string;
  created_at: string;
  metadata: {
    trigger?: string;
    agents_run?: number;
    tasks_executed?: number;
    tasks_completed?: number;
    tasks_failed?: number;
    followups_created?: number;
  };
};

type Status = {
  mode: string;
  schedule: string;
  schedule_label: string;
  cron_secret_configured: boolean;
  last_run?: Cycle | null;
};

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString() : 'Never';
}

export default function OperationsConsole() {
  const [token, setToken] = useState('');
  const [status, setStatus] = useState<Status | null>(null);
  const [history, setHistory] = useState<Cycle[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [sessionExpired, setSessionExpired] = useState(false);

  const expireSession = useCallback(() => {
    window.localStorage.removeItem(SESSION_STORAGE);
    setToken('');
    setStatus(null);
    setHistory([]);
    setSessionExpired(true);
  }, []);

  const request = useCallback(async (path: string, options: RequestInit = {}, tokenOverride?: string) => {
    const activeToken = tokenOverride || token;
    if (!activeToken) throw new Error('Sign in on the owner dashboard first.');
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${activeToken}`,
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      expireSession();
      throw new Error('Your owner session expired or was revoked. Sign in again to continue.');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, [expireSession, token]);

  const load = useCallback(async (tokenOverride?: string) => {
    setLoading(true);
    setError('');
    try {
      const [statusData, historyData] = await Promise.all([
        request('/scheduled/status', {}, tokenOverride),
        request('/scheduled/history', {}, tokenOverride),
      ]);
      setStatus(statusData);
      setHistory(historyData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load scheduled operations');
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    const stored = window.localStorage.getItem(SESSION_STORAGE) || '';
    setToken(stored);
    if (stored) void load(stored);
  }, [load]);

  async function runNow() {
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const result = await request('/scheduled/run-now', { method: 'POST', body: '{}' });
      setNotice(`Cycle completed: ${result.agents_run || 0} agents, ${result.tasks_completed || 0} tasks completed, ${result.tasks_failed || 0} failed.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to run scheduled cycle');
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return <main className={styles.setup}><section className={styles.setupCard}>
      <span className={styles.eyebrow}>CONTINUOUS OPERATIONS</span>
      <h1>{sessionExpired ? 'Owner session expired' : 'Owner session required'}</h1>
      <p>{sessionExpired ? 'Your previous session was revoked or expired. Sign in again, then return to scheduled operations.' : 'Sign in on the owner dashboard, then reopen scheduled operations.'}</p>
      <a className={styles.linkButton} href="/owner">Sign in again</a>
    </section></main>;
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div>
        <span className={styles.eyebrow}>CONTINUOUS OPERATIONS</span>
        <h1>Scheduled Operations</h1>
        <p>Monitor the daily supervised cycle and run the same tenant-safe process on demand.</p>
      </div>
      <div className={styles.actions}>
        <button className={styles.runButton} onClick={() => void runNow()} disabled={loading}>{loading ? 'Running…' : 'Run Scheduled Cycle Now'}</button>
        <button onClick={() => void load()} disabled={loading}>Refresh</button>
        <a className={styles.linkButton} href="/owner/activate">Activation Console</a>
        <a className={styles.linkButton} href="/owner">Control Plane</a>
      </div>
    </header>

    {notice && <div className={styles.notice}>{notice}</div>}
    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Mode</span><strong>{status?.mode?.replaceAll('_', ' ') || '—'}</strong></article>
      <article><span>Automatic schedule</span><strong>{status?.schedule_label || '—'}</strong></article>
      <article><span>Cron security</span><strong>{status?.cron_secret_configured ? 'Configured' : 'Missing'}</strong></article>
      <article><span>Last run</span><strong>{formatDate(status?.last_run?.created_at)}</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}>
        <div><span className={styles.eyebrow}>HISTORY</span><h2>Scheduled cycle history</h2></div>
        <small>{history.length} recorded cycles</small>
      </div>
      <div className={styles.list}>
        {history.length ? history.map(item => <div key={item.id}>
          <span>
            <b>{item.metadata?.trigger === 'owner_manual_schedule' ? 'Owner-triggered cycle' : 'Automatic scheduled cycle'}</b>
            <small>{formatDate(item.created_at)}</small>
            <small>{item.summary}</small>
          </span>
          <span className={styles.score}>
            {item.metadata?.agents_run || 0} agents · {item.metadata?.tasks_completed || 0} done · {item.metadata?.tasks_failed || 0} failed · {item.metadata?.followups_created || 0} follow-ups
          </span>
        </div>) : <p>No scheduled cycles recorded yet.</p>}
      </div>
    </section>
  </main>;
}

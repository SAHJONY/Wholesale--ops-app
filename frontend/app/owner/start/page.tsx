'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

// The session cookie is HttpOnly and middleware attaches it to same-origin
// /api/* requests, so this page never sees or stores a token.
type Step = {
  id: string;
  title: string;
  why: string;
  route: string;
  status: 'done' | 'todo' | 'blocked';
  detail: string;
  blocked_by: string | null;
};

const BADGE: Record<string, string> = {
  done: styles.healthy,
  todo: styles.score,
  blocked: styles.idle,
};

export default function StartPage() {
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [next, setNext] = useState<Step | null>(null);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/getting-started/next-steps', {
        cache: 'no-store',
        credentials: 'same-origin',
      });
      const text = await response.text();
      let body: any = {};
      if (text) { try { body = JSON.parse(text); } catch { body = { detail: text }; } }
      if (response.status === 401 || response.status === 403) {
        location.replace('/login?returnTo=/owner/start');
        return;
      }
      if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
      setSummary(body.summary || null);
      setSteps(body.steps || []);
      setNext(body.next || null);
      setNote(body.note || '');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load setup progress');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>START HERE</span>
          <h1>Getting Started</h1>
          <p>
            The console has 31 pages. This is the order they actually matter in, computed from what
            your workspace already has.
          </p>
        </div>
        <div className={styles.actions}>
          <button className={styles.runButton} onClick={() => void load()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <a className={styles.linkButton} href="/owner">Control Plane</a>
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      {summary && (
        <section className={styles.metrics}>
          <article><span>Complete</span><strong>{summary.percent_complete}%</strong></article>
          <article><span>Done</span><strong>{summary.done}</strong></article>
          <article><span>Ready to do</span><strong>{summary.actionable}</strong></article>
          <article><span>Blocked</span><strong>{summary.blocked}</strong></article>
        </section>
      )}

      {next && (
        <section className={styles.cardWide}>
          <div className={styles.cardHeader}>
            <h2>Do this next</h2>
            <span className={styles.score}>step {next.id}</span>
          </div>
          <div className={styles.list}>
            <div>
              <span>
                <b>{next.title}</b>
                <small>{next.why}</small>
                <small>{next.detail}</small>
              </span>
              <a className={styles.linkButton} href={next.route}>Open</a>
            </div>
          </div>
        </section>
      )}

      <section className={styles.cardWide}>
        <div className={styles.cardHeader}>
          <h2>Full sequence</h2>
          <small>{note}</small>
        </div>
        <div className={styles.list}>
          {steps.map(step => (
            <div key={step.id}>
              <span>
                <b>{step.title}</b>
                <small>{step.why}</small>
                <small>{step.detail}</small>
                {step.blocked_by && <small>Blocked: {step.blocked_by}</small>}
              </span>
              <span className={styles.decisionButtons}>
                <span className={BADGE[step.status]}>{step.status}</span>
                {step.status !== 'blocked' && (
                  <a className={styles.linkButton} href={step.route}>Open</a>
                )}
              </span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

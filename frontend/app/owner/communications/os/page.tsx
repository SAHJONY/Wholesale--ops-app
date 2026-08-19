'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../../owner.module.css';

const API_URL = '/api/backend';

type Readiness = {
  provider_configuration?: {
    sms_live?: boolean;
    voice_live?: boolean;
    email_send_live?: boolean;
    email_reply_live?: boolean;
  };
  production_evidence?: Record<string, number>;
  proven_live?: Record<string, boolean>;
  production_proven?: boolean;
  next_proof?: string[];
};

type Scorecard = {
  activity?: Record<string, number>;
  conversion?: Record<string, number | null>;
  management_rule?: string;
};

type Blueprint = {
  version?: string;
  operating_model?: string;
  personas?: Record<string, { label: string; mission: string; tone: string[] }>;
  languages?: Record<string, { name: string; direction: string }>;
  hard_gates?: string[];
};

function State({ ok }: { ok?: boolean }) {
  return <b>{ok ? 'READY' : 'NOT PROVEN'}</b>;
}

export default function CommunicationOsCommandCenter() {
  const [readiness, setReadiness] = useState<Readiness>({});
  const [scorecard, setScorecard] = useState<Scorecard>({});
  const [blueprint, setBlueprint] = useState<Blueprint>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = useCallback(async (path: string) => {
    const response = await fetch(`${API_URL}${path}`, {
      cache: 'no-store',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [r, s, b] = await Promise.all([
        request('/communication-os/readiness'),
        request('/communication-os/scorecard'),
        request('/communication-os/blueprint'),
      ]);
      setReadiness(r); setScorecard(s); setBlueprint(b);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Communication OS');
    } finally { setLoading(false); }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const activity = scorecard.activity || {};
  const conversion = scorecard.conversion || {};
  const providers = readiness.provider_configuration || {};
  const personas = Object.entries(blueprint.personas || {});
  const languages = Object.values(blueprint.languages || {});

  return <main className={styles.page}>
    <header className={styles.header}>
      <div>
        <span className={styles.eyebrow}>SAHJONY COMMUNICATION OS · v{blueprint.version || '10.0'}</span>
        <h1>Communication Command Center</h1>
        <p>{blueprint.operating_model || 'Permission → understand → qualify → verify → underwrite → options → respectful follow-up.'}</p>
      </div>
      <div className={styles.actions}>
        <button onClick={() => void load()} disabled={loading}>Refresh</button>
        <a className={styles.linkButton} href="/owner/communications">Execution Center</a>
        <a className={styles.linkButton} href="/owner">Control Plane</a>
      </div>
    </header>

    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>SMS provider</span><State ok={providers.sms_live} /></article>
      <article><span>Voice provider</span><State ok={providers.voice_live} /></article>
      <article><span>Email send</span><State ok={providers.email_send_live} /></article>
      <article><span>End-to-end proof</span><State ok={readiness.production_proven} /></article>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}>
        <span className={styles.eyebrow}>PRODUCTION EVIDENCE</span><h2>Real communication ledger</h2>
        <div className={styles.list}>
          {Object.entries(readiness.production_evidence || {}).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{value}</b></div>)}
        </div>
      </article>

      <article className={styles.card}>
        <span className={styles.eyebrow}>CONVERSION</span><h2>Quality, not message volume</h2>
        <div className={styles.list}>
          <div><span>SMS reply rate</span><b>{conversion.sms_reply_rate_pct == null ? '—' : `${conversion.sms_reply_rate_pct}%`}</b></div>
          <div><span>Call completion rate</span><b>{conversion.call_completion_rate_pct == null ? '—' : `${conversion.call_completion_rate_pct}%`}</b></div>
          <div><span>Appointments / outbound</span><b>{conversion.appointment_per_outbound_pct == null ? '—' : `${conversion.appointment_per_outbound_pct}%`}</b></div>
          <div><span>Opt-outs</span><b>{activity.opt_outs ?? 0}</b></div>
        </div>
        <p>{scorecard.management_rule}</p>
      </article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PERSONA ROUTING</span><h2>Specialized communication agents</h2></div><small>{personas.length} operational personas</small></div>
      <div className={styles.grid}>
        {personas.map(([key, persona]) => <article className={styles.card} key={key}>
          <b>{persona.label}</b><p>{persona.mission}</p><small>{persona.tone.join(' · ')}</small>
        </article>)}
      </div>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>WORLDWIDE LANGUAGE LAYER</span><h2>Communication-language coverage</h2></div><small>{languages.length} explicitly supported languages</small></div>
      <p>{languages.map(item => item.name).join(' · ')}</p>
      <div className={styles.calculation}>Addresses, phone/email, money, APN/legal description, title/payoff facts, instrument IDs and compliance evidence remain verbatim across languages.</div>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}>
        <span className={styles.eyebrow}>HARD GATES</span><h2>Fail-closed controls</h2>
        <ol>{(blueprint.hard_gates || []).map(item => <li key={item}>{item}</li>)}</ol>
      </article>
      <article className={styles.card}>
        <span className={styles.eyebrow}>NEXT PROOF</span><h2>What makes this truly 10/10</h2>
        <ol>{(readiness.next_proof || []).map(item => <li key={item}>{item}</li>)}</ol>
      </article>
    </section>
  </main>;
}

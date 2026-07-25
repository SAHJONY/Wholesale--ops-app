'use client';

import { FormEvent, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/public-data';
const SESSION = 'sahjony_owner_session';

type Status = {
  ready: boolean;
  mode: string;
  coverage: string;
  services: { id: string; reachable: boolean; status_code?: number | null; latency_ms: number }[];
  safety: Record<string, boolean>;
};

type Enrichment = {
  input: Record<string, string>;
  property: {
    matched_address?: string;
    coordinates?: { latitude?: number; longitude?: number };
    geography?: Record<string, string | null>;
  };
  county_context?: Record<string, string | number | null> | null;
  provenance: { provider: string; observed_at: string; confidence: string; latency_ms?: number }[];
  limitations: string[];
  workflow: { committed: boolean; dry_run: boolean; external_actions_allowed: boolean; owner_review_required: boolean };
};

export default function NationwideDataPage() {
  const [token, setToken] = useState('');
  const [status, setStatus] = useState<Status | null>(null);
  const [result, setResult] = useState<Enrichment | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ street: '', city: '', state: '', zip_code: '' });

  async function request(path: string, options: RequestInit = {}, activeToken?: string) {
    const active = activeToken || token;
    if (!active) throw new Error('Owner session required');
    const response = await fetch(`${API}/${path}`, {
      ...options,
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${active}`, ...(options.headers || {}) },
    });
    const text = await response.text();
    let body: any = {};
    if (text) { try { body = JSON.parse(text); } catch { body = { detail: text }; } }
    if (response.status === 401 || response.status === 403) {
      localStorage.removeItem(SESSION);
      location.replace('/owner-access');
      throw new Error('Owner session expired');
    }
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }

  async function loadStatus(activeToken?: string) {
    setLoading(true); setError('');
    try { setStatus(await request('nationwide/status', {}, activeToken)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Nationwide provider status unavailable'); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    const stored = localStorage.getItem(SESSION) || '';
    if (!stored) { location.replace('/owner-access'); return; }
    setToken(stored);
    void loadStatus(stored);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true); setError(''); setResult(null);
    try {
      const body = await request('nationwide/enrich-address', { method: 'POST', body: JSON.stringify(form) });
      setResult(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Address enrichment failed');
    } finally { setLoading(false); }
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>NATIONWIDE PUBLIC DATA</span><h1>Nationwide Property Context</h1><p>Resolve real U.S. addresses to Census/TIGER geography and county-level housing context without writing data or triggering external actions.</p></div>
      <div className={styles.actions}><button onClick={() => void loadStatus()} disabled={loading}>Refresh status</button><a className={styles.linkButton} href="/owner/public-data">Provider Catalog</a><a className={styles.linkButton} href="/owner">Control Plane</a></div>
    </header>

    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Mode</span><strong>{status?.mode?.replaceAll('_', ' ').toUpperCase() || 'SETUP'}</strong></article>
      <article><span>Provider status</span><strong>{status?.ready ? 'READY' : 'CHECK'}</strong></article>
      <article><span>Services</span><strong>{status?.services?.length || 0}</strong></article>
      <article><span>Database writes</span><strong>BLOCKED</strong></article>
      <article><span>Outbound actions</span><strong>BLOCKED</strong></article>
      <article><span>Texas</span><strong>EXCLUDED</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>LIVE LOOKUP</span><h2>Enrich one address</h2></div><strong>READ ONLY</strong></div>
      <form onSubmit={submit} className={styles.formGrid}>
        <label>Street<input value={form.street} onChange={e => setForm({ ...form, street: e.target.value })} required placeholder="4600 Silver Hill Rd" /></label>
        <label>City<input value={form.city} onChange={e => setForm({ ...form, city: e.target.value })} placeholder="Washington" /></label>
        <label>State<input value={form.state} onChange={e => setForm({ ...form, state: e.target.value.toUpperCase() })} required maxLength={2} placeholder="DC" /></label>
        <label>ZIP<input value={form.zip_code} onChange={e => setForm({ ...form, zip_code: e.target.value })} placeholder="20233" /></label>
        <button type="submit" disabled={loading}>{loading ? 'Checking...' : 'Run live enrichment'}</button>
      </form>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>SERVICES</span><h2>Nationwide provider health</h2></div><strong>{status?.services?.filter(service => service.reachable).length || 0}/{status?.services?.length || 0}</strong></div>
      <div className={styles.list}>{status?.services?.map(service => <div key={service.id}><span><b>{service.id.replaceAll('_', ' ')}</b><small>HTTP {service.status_code ?? 'unavailable'} · {service.latency_ms}ms</small></span><strong>{service.reachable ? 'ONLINE' : 'OFFLINE'}</strong></div>) || <p>Provider health has not loaded.</p>}</div>
    </section>

    {result && <>
      <section className={styles.cardWide}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>MATCH</span><h2>{result.property.matched_address || 'Matched property geography'}</h2></div><strong>DRY RUN</strong></div>
        <div className={styles.list}>
          <div><span><b>Coordinates</b><small>{String(result.property.coordinates?.latitude ?? 'n/a')}, {String(result.property.coordinates?.longitude ?? 'n/a')}</small></span></div>
          {Object.entries(result.property.geography || {}).map(([key, value]) => <div key={key}><span><b>{key.replaceAll('_', ' ')}</b><small>{String(value ?? 'n/a')}</small></span></div>)}
        </div>
      </section>
      <section className={styles.cardWide}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>COUNTY CONTEXT</span><h2>Aggregate housing indicators</h2></div><strong>{result.county_context ? 'AVAILABLE' : 'UNAVAILABLE'}</strong></div>
        <div className={styles.list}>{result.county_context ? Object.entries(result.county_context).map(([key, value]) => <div key={key}><span><b>{key.replaceAll('_', ' ')}</b><small>{String(value ?? 'n/a')}</small></span></div>) : <p>No county-level ACS context was returned.</p>}</div>
      </section>
      <section className={styles.cardWide}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVENANCE</span><h2>Source evidence</h2></div><strong>{result.provenance.length}</strong></div>
        <div className={styles.list}>{result.provenance.map((item, index) => <div key={`${item.provider}-${index}`}><span><b>{item.provider}</b><small>{item.confidence} · observed {new Date(item.observed_at).toLocaleString()} · {item.latency_ms ?? 'n/a'}ms</small></span></div>)}</div>
      </section>
      <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>LIMITATIONS</span><h2>Required human verification</h2></div><strong>{result.limitations.length}</strong></div><div className={styles.list}>{result.limitations.map(item => <div key={item}><span><small>{item}</small></span></div>)}</div></section>
    </>}
  </main>;
}

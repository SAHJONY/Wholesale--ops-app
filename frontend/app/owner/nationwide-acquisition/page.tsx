'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const SESSION = 'sahjony_owner_session';
const SIGN_IN = '/login?returnTo=/owner/nationwide-acquisition';

type ProviderReadiness = { ready: boolean; enabled: string[]; blocked: Array<{ id: string; missing: string }>; licensed_sources: string[]; public_sources: string[] };
type IntakeSnapshot = { required_columns: string[]; optional_columns: string[]; max_rows: number; texas_excluded: boolean; imports: Array<{ id: number; summary: string; metadata: Record<string, unknown>; created_at: string }> };
type Preview = { total_rows: number; accepted_count: number; duplicate_count: number; rejected_count: number; accepted: Array<Record<string, unknown>>; duplicates: Array<Record<string, unknown>>; rejected: Array<Record<string, unknown>> };

const TEMPLATE = `seller_name,phone,email,address,city,state,zip_code,source,notes,asking_price,arv,repairs,bedrooms,bathrooms,sqft,motivation_score,distress_score,equity_score
Jane Seller,3055550100,jane@example.com,123 Main St,Miami,FL,33101,county_tax_delinquent,Public record lead,,,,3,2,1450,70,85,75`;

export default function NationwideAcquisitionCenter() {
  const [providers, setProviders] = useState<ProviderReadiness | null>(null);
  const [intake, setIntake] = useState<IntakeSnapshot | null>(null);
  const [csvText, setCsvText] = useState(TEMPLATE);
  const [sourceLabel, setSourceLabel] = useState('county_public_records');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = useCallback(async (path: string, options: RequestInit = {}) => {
    const token = 'cookie-session';
    if (!token) { window.location.replace(SIGN_IN); throw new Error('Owner session required'); }
    const response = await fetch(`/api/backend${path}`, { ...options, cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(options.headers || {}) } });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {  window.location.replace(SIGN_IN); throw new Error('Owner session expired'); }
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
    return body;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    const [providerResult, intakeResult] = await Promise.allSettled([request('/public-data/readiness'), request('/data-intake/snapshot')]);
    if (providerResult.status === 'fulfilled') setProviders(providerResult.value);
    if (intakeResult.status === 'fulfilled') setIntake(intakeResult.value);
    const failures = [providerResult.status === 'rejected' ? `/public-data/readiness: ${providerResult.reason instanceof Error ? providerResult.reason.message : 'failed'}` : '', intakeResult.status === 'rejected' ? `/data-intake/snapshot: ${intakeResult.reason instanceof Error ? intakeResult.reason.message : 'failed'}` : ''].filter(Boolean);
    setError(failures.join(' · ')); setLoading(false);
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  async function previewImport(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError(''); setNotice('');
    try { const result = await request('/data-intake/preview', { method: 'POST', body: JSON.stringify({ csv_text: csvText }) }); setPreview(result); setNotice(`Preview complete: ${result.accepted_count} accepted, ${result.duplicate_count} duplicates, ${result.rejected_count} rejected.`); }
    catch (err) { setError(err instanceof Error ? err.message : 'Preview failed'); }
    finally { setLoading(false); }
  }

  async function commitImport() {
    if (!preview?.accepted_count) return;
    setLoading(true); setError(''); setNotice('');
    try { const result = await request('/data-intake/commit', { method: 'POST', body: JSON.stringify({ csv_text: csvText, source_label: sourceLabel }) }); setNotice(`Imported ${result.created_count} real lead(s) into the production acquisition pipeline.`); setPreview(null); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Import failed'); }
    finally { setLoading(false); }
  }

  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>NATIONWIDE ACQUISITION BUSINESS</span><h1>Launch Center</h1><p>Load verified public-record and licensed-provider opportunities into the live owner-controlled acquisition pipeline.</p></div><div className={styles.actions}><button onClick={() => void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner">CEO Command</a><a className={styles.linkButton} href="/owner/acquisition">Pipeline</a></div></header>
    {notice && <div className={styles.notice}>{notice}</div>}{error && <div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Provider framework</span><strong>{providers?.ready ? 'READY' : 'CONFIGURE'}</strong></article><article><span>Enabled sources</span><strong>{providers?.enabled?.length || 0}</strong></article><article><span>Blocked sources</span><strong>{providers?.blocked?.length || 0}</strong></article><article><span>Import capacity</span><strong>{intake?.max_rows || 5000}</strong></article><article><span>Production imports</span><strong>{intake?.imports?.length || 0}</strong></article><article><span>Texas</span><strong>{intake?.texas_excluded ? 'EXCLUDED' : 'CHECK'}</strong></article></section>
    <section className={styles.grid}>
      <article className={styles.card}><span className={styles.eyebrow}>SOURCE ACTIVATION</span><h2>Provider readiness</h2><p><b>Public sources:</b> {(providers?.public_sources || []).join(', ') || 'Loading…'}</p><p><b>Licensed sources:</b> {(providers?.licensed_sources || []).join(', ') || 'Loading…'}</p><div className={styles.list}>{(providers?.blocked || []).map(item => <div key={item.id}><span><b>{item.id}</b><small>Missing {item.missing}</small></span><strong>BLOCKED</strong></div>)}</div><small>Configure provider credentials directly in Vercel. Never paste API keys into chat or commit them.</small></article>
      <article className={styles.card}><span className={styles.eyebrow}>REAL SOURCES</span><h2>Acquisition inputs</h2><div className={styles.list}>{['County assessor and recorder exports','Tax delinquent and foreclosure lists','Code violations and vacant structures','Probate and public court records','PropStream exports','BatchData enrichment exports','Licensed MLS/IDX exports'].map(item => <div key={item}><span><b>{item}</b><small>Normalize → deduplicate → score → owner review</small></span></div>)}</div><small>Census data enriches geography and market context but does not identify legal owners or motivated sellers.</small></article>
    </section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>PRODUCTION INTAKE</span><h2>Preview and import real opportunities</h2></div><strong>{preview ? `${preview.accepted_count} ready` : 'Dry run first'}</strong></div><form onSubmit={previewImport} className={styles.activationForm}><label>Source label<input value={sourceLabel} onChange={event => setSourceLabel(event.target.value)} required /></label><label>CSV data<textarea value={csvText} onChange={event => setCsvText(event.target.value)} rows={14} required /></label><div className={styles.actions}><button type="submit" disabled={loading}>Preview and validate</button><button type="button" onClick={() => void commitImport()} disabled={loading || !preview?.accepted_count}>Commit accepted leads</button></div><small>Required columns: {(intake?.required_columns || []).join(', ') || 'seller_name, phone, address, city, state, zip_code'}</small></form>{preview && <div className={styles.metrics}><article><span>Total rows</span><strong>{preview.total_rows}</strong></article><article><span>Accepted</span><strong>{preview.accepted_count}</strong></article><article><span>Duplicates</span><strong>{preview.duplicate_count}</strong></article><article><span>Rejected</span><strong>{preview.rejected_count}</strong></article></div>}</section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>AUDIT HISTORY</span><h2>Recent production imports</h2></div><strong>{intake?.imports?.length || 0}</strong></div><div className={styles.list}>{(intake?.imports || []).map(item => <div key={item.id}><span><b>{item.summary}</b><small>{new Date(item.created_at).toLocaleString()}</small></span></div>)}{!intake?.imports?.length && <p>No production imports recorded yet.</p>}</div></section>
  </main>;
}

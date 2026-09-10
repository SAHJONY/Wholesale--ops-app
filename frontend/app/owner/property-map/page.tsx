'use client';

import Link from 'next/link';
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from './property-map.module.css';

const SIGN_IN = '/login?returnTo=/owner/property-map';

type PropertyPoint = {
  property_id: number;
  address: string;
  city: string;
  state: string;
  zip_code: string;
  latitude?: number | null;
  longitude?: number | null;
  mapped: boolean;
  status: string;
  distress_score: number;
  motivation_score: number;
  equity_score: number;
  signal_types: string[];
  confidence?: number | null;
  arv?: number | null;
  repairs?: number | null;
  mao?: number | null;
  deal_id?: number | null;
  deal_stage?: string | null;
  projected_assignment_fee?: number | null;
};

type GlobePayload = {
  generated_at: string;
  summary: { properties: number; mapped: number; unmapped: number; active_deals: number; excluded_texas: number; excluded_non_sfr: number };
  properties: PropertyPoint[];
  governance: Record<string, boolean>;
};

type TinyFishStatus = {
  configured: boolean;
  api_key_configured: boolean;
  allowed_domains: string[];
  supported_source_types: string[];
  mode: string;
};

type ResearchPreview = {
  verification_state: string;
  source_url: string;
  observed_at: string;
  research_preview: Record<string, unknown>;
  next_action: string;
};

function money(value?: number | null) {
  return value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

function markerPosition(point: PropertyPoint) {
  const longitude = Math.max(-180, Math.min(180, Number(point.longitude || 0)));
  const latitude = Math.max(-85, Math.min(85, Number(point.latitude || 0)));
  return { left: `${((longitude + 180) / 360) * 100}%`, top: `${((90 - latitude) / 180) * 100}%` };
}

function markerTone(score: number) {
  if (score >= 70) return styles.hot;
  if (score >= 40) return styles.warm;
  return styles.cool;
}

export default function PropertyIntelligenceMap() {
  const [data, setData] = useState<GlobePayload | null>(null);
  const [tinyfish, setTinyfish] = useState<TinyFishStatus | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [stateFilter, setStateFilter] = useState('ALL');
  const [minimumDistress, setMinimumDistress] = useState(0);
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourceType, setSourceType] = useState('assessor');
  const [research, setResearch] = useState<ResearchPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [researching, setResearching] = useState(false);
  const [error, setError] = useState('');

  const request = useCallback(async (path: string, options: RequestInit = {}) => {
    const response = await fetch(`/api/backend${path}`, {
      ...options,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace(SIGN_IN);
      throw new Error('Owner session required');
    }
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [globe, status] = await Promise.all([
        request('/property-intelligence/globe'),
        request('/tinyfish/status'),
      ]);
      setData(globe);
      setTinyfish(status);
      setSelectedId((current) => current ?? globe.properties?.[0]?.property_id ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to load property intelligence');
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const states = useMemo(() => Array.from(new Set((data?.properties || []).map(point => point.state))).sort(), [data]);
  const visible = useMemo(() => (data?.properties || []).filter(point =>
    (stateFilter === 'ALL' || point.state === stateFilter) && point.distress_score >= minimumDistress
  ), [data, minimumDistress, stateFilter]);
  const selected = visible.find(point => point.property_id === selectedId) || visible[0] || null;

  async function runResearch(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setResearching(true);
    setResearch(null);
    setError('');
    try {
      const preview = await request('/tinyfish/research', {
        method: 'POST',
        body: JSON.stringify({ property_id: selected.property_id, source_url: sourceUrl, source_type: sourceType }),
      });
      setResearch(preview);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'TinyFish research failed');
    } finally {
      setResearching(false);
    }
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span>PROPERTY INTELLIGENCE · GOD VIEW</span><h1>Nationwide SFR Deal Radar</h1><p>Workspace-scoped property signals, economics and governed public-record research. Texas and non-SFR assets are excluded server-side.</p></div>
      <div className={styles.actions}><button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh radar'}</button><Link href="/owner/properties">Property Evidence</Link></div>
    </header>

    {error ? <div className={styles.error}>{error}</div> : null}

    <section className={styles.metrics}>
      <article><span>Eligible SFR</span><strong>{data?.summary.properties ?? 0}</strong><small>workspace records</small></article>
      <article><span>Mapped</span><strong>{data?.summary.mapped ?? 0}</strong><small>{data?.summary.unmapped ?? 0} need coordinates</small></article>
      <article><span>Active deals</span><strong>{data?.summary.active_deals ?? 0}</strong><small>under management</small></article>
      <article><span>Policy exclusions</span><strong>{(data?.summary.excluded_texas ?? 0) + (data?.summary.excluded_non_sfr ?? 0)}</strong><small>Texas + non-SFR</small></article>
    </section>

    <section className={styles.console}>
      <article className={styles.mapPanel}>
        <div className={styles.toolbar}>
          <label>State<select value={stateFilter} onChange={event => setStateFilter(event.target.value)}><option value="ALL">All states</option>{states.map(state => <option value={state} key={state}>{state}</option>)}</select></label>
          <label>Minimum distress<select value={minimumDistress} onChange={event => setMinimumDistress(Number(event.target.value))}><option value={0}>All signals</option><option value={40}>40+</option><option value={70}>70+ hot</option></select></label>
          <span>{visible.length} visible · {visible.filter(point => point.mapped).length} mapped</span>
        </div>
        <div className={styles.worldMap} role="img" aria-label="Geographic property intelligence map">
          <div className={styles.glow} />
          <div className={styles.graticule} />
          <div className={`${styles.land} ${styles.northAmerica}`} />
          <div className={`${styles.land} ${styles.southAmerica}`} />
          <div className={`${styles.land} ${styles.europeAfrica}`} />
          <div className={`${styles.land} ${styles.asia}`} />
          <div className={`${styles.land} ${styles.australia}`} />
          {visible.filter(point => point.mapped).map(point => <button
            type="button"
            key={point.property_id}
            className={`${styles.marker} ${markerTone(point.distress_score)} ${selected?.property_id === point.property_id ? styles.selected : ''}`}
            style={markerPosition(point)}
            onClick={() => { setSelectedId(point.property_id); setResearch(null); }}
            aria-label={`${point.address}, distress ${Math.round(point.distress_score)}`}
            title={`${point.address} · distress ${Math.round(point.distress_score)}`}
          />)}
          {!data?.summary.mapped ? <div className={styles.emptyMap}><b>No verified coordinates yet</b><span>Geocode property evidence to place leads on the radar.</span></div> : null}
        </div>
        <footer><span><i className={styles.hot} /> Distress 70+</span><span><i className={styles.warm} /> Distress 40–69</span><span><i className={styles.cool} /> Lower priority</span><em>Visual prioritization only · not legal or ownership authority</em></footer>
      </article>

      <aside className={styles.detailPanel}>
        {selected ? <>
          <span className={styles.eyebrow}>SELECTED PROPERTY</span>
          <h2>{selected.address}</h2>
          <p>{selected.city}, {selected.state} {selected.zip_code}</p>
          <div className={styles.scoreRow}><div><span>Distress</span><strong>{Math.round(selected.distress_score)}</strong></div><div><span>Motivation</span><strong>{Math.round(selected.motivation_score)}</strong></div><div><span>Equity</span><strong>{Math.round(selected.equity_score)}</strong></div></div>
          <dl><div><dt>ARV</dt><dd>{money(selected.arv)}</dd></div><div><dt>Repairs</dt><dd>{money(selected.repairs)}</dd></div><div><dt>MAO</dt><dd>{money(selected.mao)}</dd></div><div><dt>Assignment</dt><dd>{money(selected.projected_assignment_fee)}</dd></div><div><dt>Deal stage</dt><dd>{selected.deal_stage || selected.status}</dd></div><div><dt>Confidence</dt><dd>{selected.confidence == null ? 'Unverified' : `${Math.round(selected.confidence * 100)}%`}</dd></div></dl>
          <div className={styles.chips}>{selected.signal_types.length ? selected.signal_types.map(signal => <span key={signal}>{signal.replaceAll('_', ' ')}</span>) : <span>No classified distress evidence</span>}</div>
          <div className={styles.detailActions}><Link href={`/owner/properties?property=${selected.property_id}`}>Open evidence</Link>{selected.mapped ? <a href={`https://www.google.com/maps/search/?api=1&query=${selected.latitude},${selected.longitude}`} target="_blank" rel="noreferrer">Satellite view</a> : null}</div>
        </> : <div className={styles.emptyDetail}>No eligible properties are available.</div>}
      </aside>
    </section>

    <section className={styles.researchPanel}>
      <div className={styles.researchIntro}><span className={styles.eyebrow}>TINYFISH · GOVERNED RESEARCH</span><h2>Official-source evidence preview</h2><p>TinyFish may navigate only allowlisted public domains. Results remain unverified, collect no contact details and never update property truth automatically.</p><div className={tinyfish?.configured ? styles.ready : styles.setup}>{tinyfish?.configured ? 'READY' : 'SETUP REQUIRED'} · {tinyfish?.allowed_domains.length || 0} allowed domains</div></div>
      <form onSubmit={runResearch} className={styles.researchForm}>
        <label>Source type<select value={sourceType} onChange={event => setSourceType(event.target.value)}>{(tinyfish?.supported_source_types || ['assessor']).map(type => <option value={type} key={type}>{type.replaceAll('_', ' ')}</option>)}</select></label>
        <label>Official source URL<input type="url" required placeholder="https://official-county-domain.gov/record/..." value={sourceUrl} onChange={event => setSourceUrl(event.target.value)} /></label>
        <button disabled={!tinyfish?.configured || !selected || researching}>{researching ? 'Researching…' : 'Run evidence preview'}</button>
        {!tinyfish?.configured ? <small>Configure TINYFISH_API_KEY and TINYFISH_ALLOWED_DOMAINS in the backend environment.</small> : <small>Allowed: {tinyfish.allowed_domains.join(', ')}</small>}
      </form>
      {research ? <article className={styles.preview}><header><div><span>UNVERIFIED PREVIEW</span><b>{new Date(research.observed_at).toLocaleString()}</b></div><a href={research.source_url} target="_blank" rel="noreferrer">Open official source</a></header><pre>{JSON.stringify(research.research_preview, null, 2)}</pre><p>{research.next_action}</p></article> : null}
    </section>
  </main>;
}

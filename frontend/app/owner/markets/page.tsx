'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const SESSION = 'sahjony_owner_session';
const API = '/api/market-selection';

type Dimension = { id: string; description: string; requires: string; default_weight: number };
type Market = {
  zip_code: string;
  states: string[];
  cities: string[];
  counties: string[];
  composite_score: number | null;
  evidence_coverage_percent: number;
  confidence: 'none' | 'low' | 'moderate' | 'high';
  scores: Record<string, number>;
  missing_dimensions: { id: string; requires: string }[];
  cash_buyers: number;
  properties: number;
  verified_properties: number;
  distress_facts: number;
  median_assignment_fee: number | null;
};

const CONFIDENCE_CLASS: Record<string, string> = {
  high: styles.healthy,
  moderate: styles.score,
  low: styles.stale,
  none: styles.idle,
};

export default function MarketsPage() {
  const [token, setToken] = useState('');
  const [dimensions, setDimensions] = useState<Dimension[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [statesInput, setStatesInput] = useState('');
  const [minBuyers, setMinBuyers] = useState('0');
  const [markets, setMarkets] = useState<Market[]>([]);
  const [unscorable, setUnscorable] = useState<{ zip_code: string; states: string[] }[]>([]);
  const [summary, setSummary] = useState<Record<string, number> | null>(null);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const request = useCallback(async (path: string, init?: RequestInit, override?: string) => {
    const active = override || token;
    if (!active) { location.replace('/owner-access'); throw new Error('Owner session required'); }
    const response = await fetch(`${API}${path}`, {
      ...init,
      cache: 'no-store',
      headers: { Authorization: `Bearer ${active}`, 'Content-Type': 'application/json' },
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
  }, [token]);

  const rank = useCallback(async (override?: string, activeWeights?: Record<string, number>) => {
    setLoading(true);
    setError('');
    try {
      const states = statesInput.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
      const body = await request('/rank', {
        method: 'POST',
        body: JSON.stringify({
          states,
          min_cash_buyers: Number(minBuyers) || 0,
          weights: activeWeights ?? weights,
        }),
      }, override);
      setMarkets(body.markets || []);
      setUnscorable(body.unscorable_markets || []);
      setSummary(body.summary || null);
      setNote(body.note || '');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ranking failed');
    } finally {
      setLoading(false);
    }
  }, [request, statesInput, minBuyers, weights]);

  useEffect(() => {
    const stored = localStorage.getItem(SESSION) || '';
    if (!stored) { location.replace('/owner-access'); return; }
    setToken(stored);
    (async () => {
      try {
        const body = await request('/criteria', undefined, stored);
        const dims: Dimension[] = body.dimensions || [];
        setDimensions(dims);
        const initial = Object.fromEntries(dims.map(d => [d.id, d.default_weight]));
        setWeights(initial);
        await rank(stored, initial);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unable to load criteria');
      }
    })();
    // Intentionally runs once on mount; rank() is re-invoked from the controls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>MARKET SELECTION</span>
          <h1>Market Selection</h1>
          <p>
            Rank markets by wholesale criteria and the depth of your own cash-buyer network.
            Dimensions without evidence are reported, never scored as zero.
          </p>
        </div>
        <div className={styles.actions}>
          <button className={styles.runButton} onClick={() => void rank()} disabled={loading}>
            {loading ? 'Ranking…' : 'Re-rank markets'}
          </button>
          <a className={styles.linkButton} href="/owner/lead-verification">Lead Verification</a>
          <a className={styles.linkButton} href="/owner">Control Plane</a>
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}
      {note && !error && <div className={styles.cycleSummary}>{note}</div>}

      {summary && (
        <section className={styles.metrics}>
          <article><span>Markets considered</span><strong>{summary.markets_considered}</strong></article>
          <article><span>Ranked</span><strong>{summary.ranked}</strong></article>
          <article><span>High confidence</span><strong>{summary.high_confidence}</strong></article>
          <article><span>Unscorable</span><strong>{summary.unscorable}</strong></article>
        </section>
      )}

      <section className={styles.cardWide}>
        <div className={styles.cardHeader}>
          <h2>Criteria</h2>
          <small>Weights are relative; the composite is a weighted mean over evidenced dimensions only.</small>
        </div>
        <div className={styles.formGrid}>
          <label>
            <span>States (comma separated, blank for all)</span>
            <input value={statesInput} onChange={e => setStatesInput(e.target.value)} placeholder="FL, GA, OH" />
          </label>
          <label>
            <span>Minimum cash buyers</span>
            <input type="number" min={0} value={minBuyers} onChange={e => setMinBuyers(e.target.value)} />
          </label>
        </div>
        <div className={styles.activationForm}>
          {dimensions.map(dimension => (
            <label key={dimension.id} title={dimension.description}>
              <span>{dimension.id.replace(/_/g, ' ')} — needs {dimension.requires.toLowerCase()}</span>
              <input
                type="number" step="0.05" min={0} max={1}
                value={weights[dimension.id] ?? dimension.default_weight}
                onChange={e => setWeights(w => ({ ...w, [dimension.id]: Number(e.target.value) }))}
              />
            </label>
          ))}
        </div>
      </section>

      <section className={styles.cardWide}>
        <div className={styles.cardHeader}>
          <h2>Ranked markets</h2>
          <strong>{markets.length}</strong>
        </div>
        <div className={styles.list}>
          {markets.length ? markets.map(market => (
            <div key={market.zip_code}>
              <span>
                <b>
                  {market.zip_code}
                  {market.cities.length ? ` · ${market.cities.join(', ')}` : ''}
                  {market.states.length ? ` · ${market.states.join('/')}` : ''}
                </b>
                <small>
                  {market.cash_buyers} cash buyer{market.cash_buyers === 1 ? '' : 's'} ·{' '}
                  {market.verified_properties}/{market.properties} verified ·{' '}
                  {market.distress_facts} distress record{market.distress_facts === 1 ? '' : 's'}
                  {market.median_assignment_fee !== null
                    ? ` · median fee $${market.median_assignment_fee.toLocaleString()}`
                    : ''}
                </small>
                <small>
                  {Object.entries(market.scores)
                    .map(([key, value]) => `${key.replace(/_/g, ' ')} ${value}`)
                    .join(' · ') || 'No dimension had evidence'}
                </small>
                {market.missing_dimensions.length > 0 && (
                  <small>
                    Not measured: {market.missing_dimensions.map(d => d.id.replace(/_/g, ' ')).join(', ')}
                  </small>
                )}
              </span>
              <span className={styles.decisionButtons}>
                <span className={CONFIDENCE_CLASS[market.confidence] || styles.idle}>
                  {market.confidence} · {market.evidence_coverage_percent}% evidence
                </span>
                <span className={styles.score}>{market.composite_score ?? '—'}</span>
              </span>
            </div>
          )) : <p>No ranked markets yet. Add cash buyers with ZIP coverage, then re-rank.</p>}
        </div>
      </section>

      {unscorable.length > 0 && (
        <section className={styles.cardWide}>
          <div className={styles.cardHeader}>
            <h2>Not yet measurable</h2>
            <small>
              Listed separately rather than ranked last: no evidence on any dimension means unexamined,
              not unattractive.
            </small>
          </div>
          <div className={styles.list}>
            {unscorable.map(market => (
              <div key={market.zip_code}>
                <span>
                  <b>{market.zip_code}{market.states.length ? ` · ${market.states.join('/')}` : ''}</b>
                  <small>No buyers, properties, distress records or verifications on file.</small>
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

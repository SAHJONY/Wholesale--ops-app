'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = 'https://backend-pi-opal-65.vercel.app';
const SESSION_STORAGE = 'sahjony_owner_session';

type Provider = {
  id: string;
  name: string;
  category: string;
  tier: string;
  state: string;
  capabilities: string[];
  missing_variables: string[];
  verification: string;
};

type Catalog = {
  strategy: Record<string, string>;
  providers: Provider[];
};

type Readiness = {
  ready_for_live_acquisition: boolean;
  ready_for_outbound: boolean;
  ready_for_contracts: boolean;
  configured_count: number;
  provider_count: number;
  blocking_integrations: Array<{ id: string; name: string; missing_variables: string[] }>;
};

export default function IntegrationsPage() {
  const [token, setToken] = useState('');
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = useCallback(async (path: string, tokenOverride?: string) => {
    const activeToken = tokenOverride || token;
    if (!activeToken) throw new Error('Owner session required');
    const response = await fetch(`${API_URL}${path}`, {
      cache: 'no-store',
      headers: { Authorization: `Bearer ${activeToken}` },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.localStorage.removeItem(SESSION_STORAGE);
      setToken('');
      throw new Error('Owner session expired. Sign in again.');
    }
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }, [token]);

  const load = useCallback(async (tokenOverride?: string) => {
    setLoading(true); setError('');
    try {
      const [catalogData, readinessData] = await Promise.all([
        request('/integrations/catalog', tokenOverride),
        request('/integrations/readiness', tokenOverride),
      ]);
      setCatalog(catalogData); setReadiness(readinessData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load integrations');
    } finally { setLoading(false); }
  }, [request]);

  useEffect(() => {
    const stored = window.localStorage.getItem(SESSION_STORAGE) || '';
    setToken(stored);
    if (stored) void load(stored);
  }, [load]);

  if (!token) return <main className={styles.setup}><section className={styles.setupCard}><h1>Owner session required</h1><p>Sign in before opening production integrations.</p><a className={styles.linkButton} href="/owner">Go to owner sign in</a></section></main>;

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>PRODUCTION DATA</span><h1>Integration Readiness</h1><p>Authoritative property data, contact enrichment, communications, contracts, and document infrastructure.</p></div>
      <div className={styles.actions}><button onClick={() => void load()} disabled={loading}>{loading ? 'Checking…' : 'Refresh'}</button><a className={styles.linkButton} href="/owner/attention">Attention Center</a><a className={styles.linkButton} href="/owner">Control Plane</a></div>
    </header>
    {error && <div className={styles.error}>{error}</div>}
    <section className={styles.metrics}>
      <article><span>Live acquisition</span><strong>{readiness?.ready_for_live_acquisition ? 'Ready' : 'Blocked'}</strong></article>
      <article><span>Outbound</span><strong>{readiness?.ready_for_outbound ? 'Ready' : 'Blocked'}</strong></article>
      <article><span>Contracts</span><strong>{readiness?.ready_for_contracts ? 'Ready' : 'Blocked'}</strong></article>
      <article><span>Providers available</span><strong>{readiness ? `${readiness.configured_count}/${readiness.provider_count}` : '—'}</strong></article>
    </section>
    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVIDER STACK</span><h2>Connection status</h2></div><small>Credentials are never displayed</small></div>
      <div className={styles.list}>{catalog?.providers.map(provider => <div key={provider.id}><span><b>{provider.name}</b><small>{provider.category.replaceAll('_', ' ')} · {provider.tier}</small><small>{provider.capabilities.join(', ')}</small><small>Verification: {provider.verification.replaceAll('_', ' ')}</small>{provider.missing_variables.length > 0 && <small>Missing: {provider.missing_variables.join(', ')}</small>}</span><span className={styles.score}>{provider.state.replaceAll('_', ' ')}</span></div>)}</div>
    </section>
  </main>;
}

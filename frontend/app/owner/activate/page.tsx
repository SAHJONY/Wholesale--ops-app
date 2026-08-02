'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = '/api/backend';
const SESSION_STORAGE = 'sahjony_owner_session';

type Lead = {
  id: number;
  seller_name: string;
  phone: string;
  email?: string;
  source: string;
  status: string;
  motivation_score: number;
  equity_score: number;
  distress_score: number;
  timeline_days?: number;
  notes?: string;
  lead_score: number;
  property?: {
    id: number;
    address: string;
    city: string;
    state: string;
    zip_code: string;
    property_type: string;
    bedrooms?: number;
    bathrooms?: number;
    sqft?: number;
    asking_price?: number;
    arv?: number;
    repairs?: number;
    mao?: number;
    distress_signals: string[];
  };
};

type Buyer = {
  id: number;
  name: string;
  company?: string;
  buyer_type: string;
  phone: string;
  email?: string;
  zip_codes: string[];
  min_price: number;
  max_price: number;
  max_rehab: number;
  closing_days: number;
  proof_of_funds_verified: boolean;
  reliability_score: number;
};

type Snapshot = { leads: Lead[]; buyers: Buyer[]; deals: Array<Record<string, unknown>> };
type ScheduledRun = {
  id: number;
  summary: string;
  created_at: string;
  metadata: {
    agents_run?: number;
    tasks_executed?: number;
    tasks_completed?: number;
    tasks_failed?: number;
    followups_created?: number;
  };
};

function numberValue(form: FormData, name: string) {
  const value = String(form.get(name) || '').trim();
  return value === '' ? null : Number(value);
}

export default function ActivationConsole() {
  const [token, setToken] = useState('');
  const [snapshot, setSnapshot] = useState<Snapshot>({ leads: [], buyers: [], deals: [] });
  const [history, setHistory] = useState<ScheduledRun[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const selectedLead = useMemo(
    () => snapshot.leads.find(item => item.id === selectedLeadId) || snapshot.leads[0],
    [snapshot.leads, selectedLeadId],
  );

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
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, [token]);

  const load = useCallback(async (tokenOverride?: string) => {
    setLoading(true); setError('');
    try {
      const [data, scheduledHistory] = await Promise.all([
        request('/activation/snapshot', {}, tokenOverride),
        request('/scheduled/history', {}, tokenOverride),
      ]);
      setSnapshot(data);
      setHistory(scheduledHistory);
      if (!selectedLeadId && data.leads?.length) setSelectedLeadId(data.leads[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load activation console');
    } finally { setLoading(false); }
  }, [request, selectedLeadId]);

  useEffect(() => {
    const stored = 'cookie-session';
    setToken(stored);
    if (stored) void load(stored);
  }, [load]);

  async function saveLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedLead) return;
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request(`/activation/leads/${selectedLead.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          seller_name: form.get('seller_name'),
          phone: form.get('phone'),
          email: form.get('email'),
          source: form.get('source'),
          motivation_score: numberValue(form, 'motivation_score'),
          equity_score: numberValue(form, 'equity_score'),
          distress_score: numberValue(form, 'distress_score'),
          timeline_days: numberValue(form, 'timeline_days'),
          notes: form.get('notes'),
          property: {
            address: form.get('address'), city: form.get('city'), state: form.get('state'), zip_code: form.get('zip_code'),
            property_type: form.get('property_type'), bedrooms: numberValue(form, 'bedrooms'), bathrooms: numberValue(form, 'bathrooms'),
            sqft: numberValue(form, 'sqft'), asking_price: numberValue(form, 'asking_price'), arv: numberValue(form, 'arv'), repairs: numberValue(form, 'repairs'),
            distress_signals: String(form.get('distress_signals') || '').split(',').map(item => item.trim()).filter(Boolean),
          },
        }),
      });
      setNotice(`Lead updated. Score ${Math.round(result.lead_score)} · ${result.status}${result.deal_id ? ` · Deal #${result.deal_id} created` : ''}.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to update lead'); }
    finally { setLoading(false); }
  }

  async function addBuyer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request('/activation/buyers', {
        method: 'POST',
        body: JSON.stringify({
          name: form.get('name'), company: form.get('company'), buyer_type: form.get('buyer_type'), phone: form.get('phone'), email: form.get('email'),
          zip_codes: String(form.get('zip_codes') || '').split(',').map(item => item.trim()).filter(Boolean),
          asset_types: ['single_family'], min_price: numberValue(form, 'min_price'), max_price: numberValue(form, 'max_price'),
          max_rehab: numberValue(form, 'max_rehab'), closing_days: numberValue(form, 'closing_days'),
          proof_of_funds_verified: form.get('proof_of_funds_verified') === 'on', reliability_score: numberValue(form, 'reliability_score'),
        }),
      });
      formElement.reset();
      setNotice(`Buyer buy box created: ${result.name}.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create buyer'); }
    finally { setLoading(false); }
  }

  async function runSpecialists() {
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request('/activation/run-specialists', { method: 'POST', body: '{}' });
      setNotice(`${result.ran} specialist agents completed a supervised operating pass.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Specialist cycle failed'); }
    finally { setLoading(false); }
  }

  if (!token) return <main className={styles.setup}><section className={styles.setupCard}><h1>Owner session required</h1><p>Sign in on the owner dashboard, then reopen this activation console.</p><a className={styles.linkButton} href="/owner">Go to owner sign in</a></section></main>;

  const latestScheduled = history[0];

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>OPERATIONAL ACTIVATION</span><h1>Wholesale Workforce Console</h1><p>Qualify leads, underwrite property, build buyer demand, and activate specialist agents.</p></div>
      <div className={styles.actions}><button onClick={() => void runSpecialists()} disabled={loading}>{loading ? 'Working…' : 'Run All Specialist Agents'}</button><button onClick={() => void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner">Back to Control Plane</a></div>
    </header>
    {notice && <div className={styles.notice}>{notice}</div>}{error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Leads</span><strong>{snapshot.leads.length}</strong></article>
      <article><span>Qualified buyers</span><strong>{snapshot.buyers.length}</strong></article>
      <article><span>Deals</span><strong>{snapshot.deals.length}</strong></article>
      <article><span>Selected score</span><strong>{Math.round(selectedLead?.lead_score || 0)}</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>CONTINUOUS OPERATIONS</span><h2>Scheduled cycle history</h2></div><small>{latestScheduled ? `Last run ${new Date(latestScheduled.created_at).toLocaleString()}` : 'No scheduled cycle recorded yet'}</small></div>
      <div className={styles.list}>{history.length ? history.slice(0, 10).map(item => <div key={item.id}><span><b>{item.summary}</b><small>{new Date(item.created_at).toLocaleString()} · {item.metadata.agents_run || 0} agents · {item.metadata.followups_created || 0} follow-ups</small></span><span className={styles.score}>{item.metadata.tasks_completed || 0} done · {item.metadata.tasks_failed || 0} failed</span></div>) : <p>The first secured Vercel cron run will appear here after deployment and CRON_SECRET configuration.</p>}</div>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>LEAD QUALIFICATION</span><h2>Seller and property facts</h2></div><select value={selectedLead?.id || ''} onChange={e => setSelectedLeadId(Number(e.target.value))}>{snapshot.leads.map(item => <option key={item.id} value={item.id}>{item.seller_name} · {item.status}</option>)}</select></div>
        {selectedLead ? <form key={selectedLead.id} onSubmit={saveLead} className={styles.activationForm}>
          <input name="seller_name" defaultValue={selectedLead.seller_name} placeholder="Seller name" required />
          <input name="phone" defaultValue={selectedLead.phone} placeholder="Phone" required />
          <input name="email" type="email" defaultValue={selectedLead.email || ''} placeholder="Email" />
          <input name="source" defaultValue={selectedLead.source} placeholder="Lead source" />
          <label>Motivation score<input name="motivation_score" type="number" min="0" max="100" defaultValue={selectedLead.motivation_score} /></label>
          <label>Equity score<input name="equity_score" type="number" min="0" max="100" defaultValue={selectedLead.equity_score} /></label>
          <label>Distress score<input name="distress_score" type="number" min="0" max="100" defaultValue={selectedLead.distress_score} /></label>
          <label>Timeline days<input name="timeline_days" type="number" min="0" defaultValue={selectedLead.timeline_days ?? ''} /></label>
          <input name="address" defaultValue={selectedLead.property?.address || ''} placeholder="Property address" required />
          <input name="city" defaultValue={selectedLead.property?.city || ''} placeholder="City" required />
          <input name="state" defaultValue={selectedLead.property?.state || ''} placeholder="State" maxLength={2} required />
          <input name="zip_code" defaultValue={selectedLead.property?.zip_code || ''} placeholder="ZIP" required />
          <input name="property_type" defaultValue={selectedLead.property?.property_type || 'single_family'} placeholder="Property type" />
          <input name="bedrooms" type="number" defaultValue={selectedLead.property?.bedrooms ?? ''} placeholder="Bedrooms" />
          <input name="bathrooms" type="number" step="0.5" defaultValue={selectedLead.property?.bathrooms ?? ''} placeholder="Bathrooms" />
          <input name="sqft" type="number" defaultValue={selectedLead.property?.sqft ?? ''} placeholder="Square feet" />
          <input name="asking_price" type="number" defaultValue={selectedLead.property?.asking_price ?? ''} placeholder="Asking price" />
          <input name="arv" type="number" defaultValue={selectedLead.property?.arv ?? ''} placeholder="ARV" />
          <input name="repairs" type="number" defaultValue={selectedLead.property?.repairs ?? ''} placeholder="Repairs" />
          <input name="distress_signals" defaultValue={(selectedLead.property?.distress_signals || []).join(', ')} placeholder="Distress signals, comma separated" />
          <textarea name="notes" defaultValue={selectedLead.notes || ''} placeholder="Qualification notes" rows={4} />
          <button disabled={loading}>Save, score, and dispatch</button>
          <div className={styles.calculation}>Current score: <b>{Math.round(selectedLead.lead_score)}</b> · Current MAO: <b>{selectedLead.property?.mao ? `$${Math.round(selectedLead.property.mao).toLocaleString()}` : 'Needs ARV and repairs'}</b></div>
        </form> : <p>No workspace leads found.</p>}
      </article>

      <article className={styles.card}>
        <span className={styles.eyebrow}>BUYER INTELLIGENCE</span><h2>Add cash buyer buy box</h2>
        <form onSubmit={addBuyer} className={styles.activationForm}>
          <input name="name" placeholder="Buyer name" required /><input name="company" placeholder="Company" />
          <select name="buyer_type" defaultValue="cash_buyer"><option value="cash_buyer">Cash buyer</option><option value="flipper">Flipper</option><option value="landlord">Landlord</option><option value="institutional">Institutional</option><option value="hedge_fund">Hedge fund</option></select>
          <input name="phone" placeholder="Phone" required /><input name="email" type="email" placeholder="Email" />
          <input name="zip_codes" placeholder="ZIP codes: 33101, 33125" />
          <input name="min_price" type="number" placeholder="Minimum price" /><input name="max_price" type="number" placeholder="Maximum price" />
          <input name="max_rehab" type="number" placeholder="Maximum rehab" /><input name="closing_days" type="number" defaultValue="14" placeholder="Closing days" />
          <input name="reliability_score" type="number" min="0" max="100" defaultValue="50" placeholder="Reliability score" />
          <label className={styles.checkLabel}><input name="proof_of_funds_verified" type="checkbox" /> Proof of funds verified</label>
          <button disabled={loading}>Create buyer profile</button>
        </form>
        <div className={styles.list}>{snapshot.buyers.length ? snapshot.buyers.map(item => <div key={item.id}><span><b>{item.name}</b><small>{item.company || item.buyer_type} · {(item.zip_codes || []).join(', ') || 'No ZIPs'}</small><small>${item.min_price.toLocaleString()}–${item.max_price.toLocaleString()} · {item.closing_days} days</small></span><strong>{Math.round(item.reliability_score)}</strong></div>) : <p>No qualified buyers yet.</p>}</div>
      </article>
    </section>
  </main>;
}

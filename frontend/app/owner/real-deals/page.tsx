'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from './real-deals.module.css';

const SIGN_IN = '/login?returnTo=/owner/real-deals';

type SourceRef = { provider: string; source_type: string; reference: string; observed_at?: string; confidence?: number };
type PropertyView = { address?: string; city?: string; state?: string; zip_code?: string; property_type?: string; bedrooms?: number; bathrooms?: number; sqft?: number; asking_price?: number; arv?: number; repairs?: number; mao?: number; distress_signals?: string[] };
type RealDeal = {
  deal_id: number; lead_id?: number; property_id?: number; stage: string;
  owner: { name?: string; type?: string; mailing_address?: string; verified?: boolean };
  deed: { parcel_id?: string; type?: string; date?: string; consideration?: number; instrument?: string };
  property: PropertyView;
  underwriting: { target_contract_price?: number; target_buyer_price?: number; projected_assignment_fee?: number; minimum_assignment_fee?: number; meets_10k_target?: boolean; probability_to_close?: number; risk_score?: number };
  sources: SourceRef[]; source_confidence: number; verification: Record<string, unknown>; next_action?: string;
};
type Candidate = {
  lead_id: number; property_id: number; status: string;
  owner: { name?: string; type?: string; mailing_address?: string; verified?: boolean; verification_status?: string; confidence?: number };
  deed: { parcel_id?: string; date?: string; consideration?: number };
  property: PropertyView;
  screening: { factor: number; theoretical_buyer_price: number; asking_price: number; projected_assignment_spread: number; minimum_assignment_fee: number; formula: string; authority: string };
  sources: SourceRef[]; source_count: number; next_action: string;
};
type ListResponse = { count: number; deals: RealDeal[] };
type CandidateResponse = { count: number; candidates: Candidate[] };

const emptyForm = {
  owner_name: '', owner_mailing_address: '', parcel_id: '', deed_type: '', deed_date: '', deed_consideration: '', deed_instrument: '',
  address: '', city: '', state: '', zip_code: '', bedrooms: '', bathrooms: '', sqft: '', asking_price: '', arv: '', repairs: '',
  target_contract_price: '', target_buyer_price: '', distress_signals: '', source_provider: '', source_type: 'public_record', source_reference: '', notes: '',
};

function money(value?: number) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0); }
function pct(value?: number) { return `${Math.round((value || 0) * 100)}%`; }
function n(value: string) { if (!value.trim()) return undefined; const parsed = Number(value); return Number.isFinite(parsed) ? parsed : undefined; }

export default function RealDealsPage() {
  const [deals, setDeals] = useState<RealDeal[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [promoting, setPromoting] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`/api/backend${path}`, { ...init, cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer cookie-session', ...(init?.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) { window.location.replace(SIGN_IN); throw new Error('Owner session required'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const dealQuery = new URLSearchParams({ property_type: 'single_family', owner_type: 'individual', min_assignment_fee: '10000' });
      const candidateQuery = new URLSearchParams({ factor: '0.70', min_assignment_fee: '10000' });
      if (stateFilter.trim()) { dealQuery.set('state', stateFilter.trim().toUpperCase()); candidateQuery.set('state', stateFilter.trim().toUpperCase()); }
      const [dealData, candidateData] = await Promise.all([
        request(`/wholesale/real-deals?${dealQuery.toString()}`) as Promise<ListResponse>,
        request(`/wholesale/real-deal-candidates?${candidateQuery.toString()}`) as Promise<CandidateResponse>,
      ]);
      setDeals(Array.isArray(dealData.deals) ? dealData.deals : []);
      setCandidates(Array.isArray(candidateData.candidates) ? candidateData.candidates : []);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to load real-deal intelligence'); }
    finally { setLoading(false); }
  }, [request, stateFilter]);

  useEffect(() => { void load(); }, [load]);

  const totals = useMemo(() => ({
    count: deals.length,
    candidates: candidates.length,
    spread: deals.reduce((sum, deal) => sum + Number(deal.underwriting.projected_assignment_fee || 0), 0),
    candidateSpread: candidates.reduce((sum, item) => sum + Number(item.screening.projected_assignment_spread || 0), 0),
  }), [deals, candidates]);

  async function promote(propertyId: number) {
    setPromoting(propertyId); setError('');
    try { await request(`/wholesale/real-deal-candidates/${propertyId}/promote`, { method: 'POST', body: JSON.stringify({ minimum_assignment_fee: 10000, factor: 0.70 }) }); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to promote candidate'); }
    finally { setPromoting(null); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError('');
    try {
      await request('/wholesale/real-deals', { method: 'POST', body: JSON.stringify({
        owner_name: form.owner_name, owner_type: 'individual', owner_verified: true, owner_mailing_address: form.owner_mailing_address || null,
        parcel_id: form.parcel_id || null, deed_type: form.deed_type || null, deed_date: form.deed_date || null, deed_consideration: n(form.deed_consideration), deed_instrument: form.deed_instrument || null,
        address: form.address, city: form.city, state: form.state, zip_code: form.zip_code, property_type: 'single_family', bedrooms: n(form.bedrooms), bathrooms: n(form.bathrooms), sqft: n(form.sqft),
        asking_price: n(form.asking_price), arv: n(form.arv), repairs: n(form.repairs), target_contract_price: n(form.target_contract_price), target_buyer_price: n(form.target_buyer_price), minimum_assignment_fee: 10000,
        distress_signals: form.distress_signals.split(',').map(x => x.trim()).filter(Boolean), notes: form.notes || null, source_name: 'verified_real_deal_intake',
        sources: [{ provider: form.source_provider, source_type: form.source_type, reference: form.source_reference, confidence: 0.9 }],
      }) });
      setForm(emptyForm); await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to save deal'); }
    finally { setSaving(false); }
  }

  return <main className={styles.page}>
    <header className={styles.hero}><div><span>SAHJONY WHOLESALE OS · REAL DEAL INTELLIGENCE</span><h1>Verified properties, verified individual owners, real underwriting.</h1><p>Canonical public-record intelligence now screens existing properties automatically. A candidate is not an offer: title, comps, rehab and buyer demand still require validation.</p></div><div className={styles.heroActions}><a href="/owner">CEO Command</a><button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh intelligence'}</button></div></header>
    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.kpis}>
      <article><span>Promoted real deals</span><strong>{totals.count}</strong><small>Individual-owned SFR only</small></article>
      <article><span>Verified candidates</span><strong>{totals.candidates}</strong><small>Canonical intelligence screening</small></article>
      <article><span>Promoted assignment spread</span><strong>{money(totals.spread)}</strong><small>Human-controlled deal pipeline</small></article>
      <article><span>Candidate screening spread</span><strong>{money(totals.candidateSpread)}</strong><small>Screening only · not an offer</small></article>
    </section>

    <section className={styles.filterBar}><div><b>Nationwide buy box</b><span>Single-family · Individual owner · Verified public record · No owner conflict · $10K+ screening spread</span></div><label>State<input value={stateFilter} maxLength={2} placeholder="FL" onChange={e => setStateFilter(e.target.value.toUpperCase())}/></label></section>

    <section className={styles.candidateSection}>
      <div className={styles.sectionTitle}><div><span>CANONICAL INTELLIGENCE</span><h2>Verified deal candidates</h2><p>Derived from existing property intelligence. The 70% factor is a screening rule only; promotion does not authorize an offer.</p></div></div>
      <div className={styles.grid}>
        {candidates.map(item => <article className={`${styles.card} ${styles.candidateCard}`} key={item.property_id}>
          <div className={styles.cardTop}><div><span>CANDIDATE · PROPERTY #{item.property_id}</span><h2>{item.property.address}</h2><p>{item.property.city}, {item.property.state} {item.property.zip_code}</p></div><strong>{money(item.screening.projected_assignment_spread)}</strong></div>
          <div className={styles.badges}><span>Individual owner</span><span>{item.owner.verification_status || 'verified'}</span><span>No owner conflict</span>{(item.property.distress_signals || []).slice(0, 3).map(signal => <span key={signal}>{signal}</span>)}</div>
          <div className={styles.metrics}>
            <div><span>Asking</span><b>{money(item.property.asking_price)}</b></div><div><span>ARV</span><b>{money(item.property.arv)}</b></div><div><span>Repairs</span><b>{money(item.property.repairs)}</b></div>
            <div><span>Screening buyer price</span><b>{money(item.screening.theoretical_buyer_price)}</b></div><div><span>Screening factor</span><b>{Math.round(item.screening.factor * 100)}%</b></div><div><span>Potential spread</span><b className={styles.profit}>{money(item.screening.projected_assignment_spread)}</b></div>
          </div>
          <div className={styles.ownerPanel}><div><span>OWNER OF RECORD</span><b>{item.owner.name}</b><small>{item.owner.mailing_address || 'Mailing address not captured'} · confidence {Math.round(Number(item.owner.confidence || 0))}%</small></div><div><span>PUBLIC RECORD</span><b>{item.deed.parcel_id ? `APN ${item.deed.parcel_id}` : 'APN pending'}</b><small>{item.deed.date ? `Last sale ${item.deed.date}` : 'Sale date pending'}{item.deed.consideration ? ` · ${money(item.deed.consideration)}` : ''}</small></div></div>
          <div className={styles.sourceBlock}><span>PROVENANCE · {item.source_count} source{item.source_count === 1 ? '' : 's'}</span>{(item.sources || []).slice(0, 3).map((source, index) => <p key={`${source.provider}-${index}`}><b>{source.provider}</b> · {source.source_type}<small>{source.reference}</small></p>)}</div>
          <footer><span>{item.next_action}</span><button className={styles.promote} disabled={promoting === item.property_id} onClick={() => void promote(item.property_id)}>{promoting === item.property_id ? 'Promoting…' : 'Promote to real deal'}</button></footer>
        </article>)}
        {!loading && !candidates.length && <div className={styles.empty}><h2>No verified candidates pass the current gate.</h2><p>Properties need an individual owner fact, no owner conflict, asking price, ARV, repairs and at least $10K screening spread.</p></div>}
      </div>
    </section>

    <section className={styles.candidateSection}><div className={styles.sectionTitle}><div><span>DEAL PIPELINE</span><h2>Promoted real wholesale deals</h2><p>These passed the intake gate, but consequential seller offers remain human controlled.</p></div></div><div className={styles.grid}>
      {deals.map(deal => <article className={styles.card} key={deal.deal_id}>
        <div className={styles.cardTop}><div><span>DEAL #{deal.deal_id}</span><h2>{deal.property.address}</h2><p>{deal.property.city}, {deal.property.state} {deal.property.zip_code}</p></div><strong>{money(deal.underwriting.projected_assignment_fee)}</strong></div>
        <div className={styles.badges}><span>Individual owner</span><span>Source verified</span><span>Single-family</span>{(deal.property.distress_signals || []).slice(0, 3).map(signal => <span key={signal}>{signal}</span>)}</div>
        <div className={styles.metrics}><div><span>Asking</span><b>{money(deal.property.asking_price)}</b></div><div><span>ARV</span><b>{money(deal.property.arv)}</b></div><div><span>Repairs</span><b>{money(deal.property.repairs)}</b></div><div><span>Seller contract</span><b>{money(deal.underwriting.target_contract_price)}</b></div><div><span>Buyer price / MAO</span><b>{money(deal.underwriting.target_buyer_price)}</b></div><div><span>Assignment</span><b className={styles.profit}>{money(deal.underwriting.projected_assignment_fee)}</b></div></div>
        <div className={styles.ownerPanel}><div><span>OWNER OF RECORD</span><b>{deal.owner.name || 'Owner pending'}</b><small>{deal.owner.mailing_address || 'Mailing address not captured'}</small></div><div><span>LAST DEED</span><b>{deal.deed.type || 'Deed/source intelligence'} {deal.deed.date ? `· ${deal.deed.date}` : ''}</b><small>{deal.deed.consideration ? `${money(deal.deed.consideration)} consideration` : 'Consideration pending'} {deal.deed.parcel_id ? `· APN ${deal.deed.parcel_id}` : ''}</small></div></div>
        <div className={styles.sourceBlock}><span>PROVENANCE · {pct(deal.source_confidence)}</span>{(deal.sources || []).slice(0, 3).map((source, index) => <p key={`${source.provider}-${index}`}><b>{source.provider}</b> · {source.source_type}<small>{source.reference}</small></p>)}</div>
        <footer><span>{deal.next_action || 'Verify title and buyer before offer.'}</span><a href={`/owner/deals?deal=${deal.deal_id}`}>Open deal →</a></footer>
      </article>)}
      {!loading && !deals.length && <div className={styles.empty}><h2>No deals promoted yet.</h2><p>Promote a verified candidate above or add a source-grounded deal manually below.</p></div>}
    </div></section>

    <section className={styles.intake}><div className={styles.intakeIntro}><span>MANUAL VERIFIED INTAKE</span><h2>Add a real property when the canonical pipeline does not have it yet.</h2><p>The API rejects entity owners and projected spreads below $10,000. Owner identity should come from a deed, property appraiser, clerk, or equivalent public record.</p></div><form onSubmit={submit}>
      <h3>Owner + deed</h3><div className={styles.formGrid}>
        <label>Owner of record<input required value={form.owner_name} onChange={e => setForm({...form, owner_name:e.target.value})}/></label><label>Owner mailing address<input value={form.owner_mailing_address} onChange={e => setForm({...form, owner_mailing_address:e.target.value})}/></label><label>Parcel / APN<input value={form.parcel_id} onChange={e => setForm({...form, parcel_id:e.target.value})}/></label><label>Deed type<input value={form.deed_type} placeholder="Warranty Deed" onChange={e => setForm({...form, deed_type:e.target.value})}/></label><label>Deed date<input type="date" value={form.deed_date} onChange={e => setForm({...form, deed_date:e.target.value})}/></label><label>Deed consideration<input type="number" min="0" value={form.deed_consideration} onChange={e => setForm({...form, deed_consideration:e.target.value})}/></label>
      </div><h3>Property + underwriting</h3><div className={styles.formGrid}>
        <label>Street address<input required value={form.address} onChange={e => setForm({...form, address:e.target.value})}/></label><label>City<input required value={form.city} onChange={e => setForm({...form, city:e.target.value})}/></label><label>State<input required maxLength={2} value={form.state} onChange={e => setForm({...form, state:e.target.value.toUpperCase()})}/></label><label>ZIP<input required value={form.zip_code} onChange={e => setForm({...form, zip_code:e.target.value})}/></label><label>Beds<input type="number" min="0" value={form.bedrooms} onChange={e => setForm({...form, bedrooms:e.target.value})}/></label><label>Baths<input type="number" min="0" step="0.5" value={form.bathrooms} onChange={e => setForm({...form, bathrooms:e.target.value})}/></label><label>Sqft<input type="number" min="0" value={form.sqft} onChange={e => setForm({...form, sqft:e.target.value})}/></label><label>Asking price<input type="number" min="0" value={form.asking_price} onChange={e => setForm({...form, asking_price:e.target.value})}/></label><label>ARV<input required type="number" min="1" value={form.arv} onChange={e => setForm({...form, arv:e.target.value})}/></label><label>Repairs<input required type="number" min="0" value={form.repairs} onChange={e => setForm({...form, repairs:e.target.value})}/></label><label>Target seller contract<input required type="number" min="1" value={form.target_contract_price} onChange={e => setForm({...form, target_contract_price:e.target.value})}/></label><label>Target buyer price<input required type="number" min="1" value={form.target_buyer_price} onChange={e => setForm({...form, target_buyer_price:e.target.value})}/></label><label className={styles.wide}>Distress signals<input value={form.distress_signals} placeholder="vacant, probate, foreclosure, price reductions" onChange={e => setForm({...form, distress_signals:e.target.value})}/></label>
      </div><h3>Source provenance</h3><div className={styles.formGrid}><label>Provider / county<input required value={form.source_provider} placeholder="Escambia County Clerk" onChange={e => setForm({...form, source_provider:e.target.value})}/></label><label>Source type<input required value={form.source_type} onChange={e => setForm({...form, source_type:e.target.value})}/></label><label className={styles.wide}>Source reference<input required value={form.source_reference} placeholder="Instrument number, official-record URL, MLS ID, court case, etc." onChange={e => setForm({...form, source_reference:e.target.value})}/></label><label className={styles.wide}>Notes<textarea value={form.notes} onChange={e => setForm({...form, notes:e.target.value})}/></label></div><button className={styles.save} disabled={saving}>{saving ? 'Validating…' : 'Validate and add real deal'}</button>
    </form></section>
  </main>;
}

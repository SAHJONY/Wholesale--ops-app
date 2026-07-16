'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://backend-pi-opal-65.vercel.app';

type Stats = { total_leads: number; hot_leads: number; buyers: number; calls: number };
type Lead = { id: number; seller_name: string; phone: string; status: string; distress_score: number; motivation_score: number; address?: string; zip_code?: string; mao?: number };
type Match = { buyer_id: number; buyer_name: string; score: number; reasons: string[] };

type Notice = { kind: 'success' | 'error'; text: string } | null;

const navItems = ['Command Center', 'Leads', 'Cash Buyers', 'Underwriting', 'Buyer Matching', 'Bland Calls', 'Driving for Dollars'];

function money(value?: number) {
  if (value === undefined || value === null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

export default function Home() {
  const [active, setActive] = useState('Command Center');
  const [stats, setStats] = useState<Stats>({ total_leads: 0, hot_leads: 0, buyers: 0, calls: 0 });
  const [leads, setLeads] = useState<Lead[]>([]);
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'offline'>('checking');
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);
  const [matches, setMatches] = useState<Match[]>([]);
  const [matchPropertyId, setMatchPropertyId] = useState('1');
  const [underwriteResult, setUnderwriteResult] = useState<{ mao: number } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [dashboardResponse, leadsResponse] = await Promise.all([
        fetch(`${API_URL}/dashboard`, { cache: 'no-store' }),
        fetch(`${API_URL}/leads`, { cache: 'no-store' }),
      ]);
      if (!dashboardResponse.ok || !leadsResponse.ok) throw new Error('API request failed');
      setStats(await dashboardResponse.json());
      setLeads(await leadsResponse.json());
      setApiStatus('connected');
    } catch {
      setApiStatus('offline');
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function post(path: string, body: unknown) {
    setLoading(true);
    setNotice(null);
    try {
      const response = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : 'Request failed');
      setNotice({ kind: 'success', text: 'Saved successfully.' });
      await refresh();
      return data;
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Request failed' });
      throw error;
    } finally {
      setLoading(false);
    }
  }

  async function createLead(event: FormEvent<HTMLFormElement>, source = 'manual') {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await post(source === 'driving_for_dollars' ? '/driving-for-dollars' : '/leads', {
      seller_name: form.get('seller_name'),
      phone: form.get('phone'),
      email: form.get('email') || null,
      source,
      motivation_score: Number(form.get('motivation_score') || 0),
      equity_score: Number(form.get('equity_score') || 0),
      timeline_days: Number(form.get('timeline_days') || 30),
      notes: form.get('notes') || null,
      property: {
        address: form.get('address'), city: form.get('city'), state: form.get('state'), zip_code: form.get('zip_code'),
        property_type: 'single_family', bedrooms: Number(form.get('bedrooms') || 0), bathrooms: Number(form.get('bathrooms') || 0),
        sqft: Number(form.get('sqft') || 0), asking_price: Number(form.get('asking_price') || 0),
        arv: Number(form.get('arv') || 0), repairs: Number(form.get('repairs') || 0),
        distress_signals: String(form.get('distress_signals') || '').split(',').map(v => v.trim()).filter(Boolean),
        latitude: form.get('latitude') ? Number(form.get('latitude')) : null,
        longitude: form.get('longitude') ? Number(form.get('longitude')) : null,
      },
    });
    event.currentTarget.reset();
  }

  async function createBuyer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await post('/buyers', {
      name: form.get('name'), company: form.get('company') || null, buyer_type: form.get('buyer_type'),
      phone: form.get('phone'), email: form.get('email') || null,
      zip_codes: String(form.get('zip_codes') || '').split(',').map(v => v.trim()).filter(Boolean),
      asset_types: ['single_family'], min_price: Number(form.get('min_price') || 0), max_price: Number(form.get('max_price') || 10000000),
      max_rehab: Number(form.get('max_rehab') || 500000), closing_days: Number(form.get('closing_days') || 14),
      proof_of_funds_verified: form.get('proof_of_funds_verified') === 'on', response_rate: Number(form.get('response_rate') || 0),
      reliability_score: Number(form.get('reliability_score') || 50),
    });
    event.currentTarget.reset();
  }

  async function underwrite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const data = await post('/underwrite', {
      arv: Number(form.get('arv')), repairs: Number(form.get('repairs')),
      assignment_fee: Number(form.get('assignment_fee')), mao_factor: Number(form.get('mao_factor')),
    });
    setUnderwriteResult(data);
  }

  async function runMatch() {
    setLoading(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/properties/${matchPropertyId}/matches`, { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Match failed');
      setMatches(data);
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Match failed' });
    } finally { setLoading(false); }
  }

  async function testBland(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await post('/webhooks/bland', {
      call_id: form.get('call_id'), direction: form.get('direction'), status: form.get('status'), summary: form.get('summary'),
    });
  }

  const panels = useMemo(() => ({
    'Command Center': <CommandCenter stats={stats} leads={leads} apiStatus={apiStatus} onNavigate={setActive} onRefresh={refresh} />,
    'Leads': <LeadsPanel leads={leads} onSubmit={createLead} loading={loading} />,
    'Cash Buyers': <BuyerPanel onSubmit={createBuyer} loading={loading} />,
    'Underwriting': <UnderwritePanel onSubmit={underwrite} loading={loading} result={underwriteResult} />,
    'Buyer Matching': <MatchPanel propertyId={matchPropertyId} setPropertyId={setMatchPropertyId} onMatch={runMatch} matches={matches} loading={loading} />,
    'Bland Calls': <BlandPanel onSubmit={testBland} loading={loading} />,
    'Driving for Dollars': <DrivingPanel onSubmit={(e) => createLead(e, 'driving_for_dollars')} loading={loading} />,
  }), [stats, leads, apiStatus, loading, underwriteResult, matches, matchPropertyId, refresh]);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">SAHJONY</div><p>Wholesale Operations</p>
        <nav>{navItems.map(item => <button key={item} className={active === item ? 'active' : ''} onClick={() => setActive(item)}>{item}</button>)}</nav>
        <div className={`apiBadge ${apiStatus}`}>API {apiStatus}</div>
      </aside>
      <section className="workspace">
        <header className="topbar"><div><span className="eyebrow">AUTONOMOUS WORKFORCE</span><h1>{active}</h1><p>Live residential and commercial wholesale operations.</p></div><button className="primary" onClick={() => setActive('Leads')}>+ Add Lead</button></header>
        {notice && <div className={`notice ${notice.kind}`}>{notice.text}</div>}
        {panels[active as keyof typeof panels]}
      </section>
    </main>
  );
}

function CommandCenter({ stats, leads, apiStatus, onNavigate, onRefresh }: { stats: Stats; leads: Lead[]; apiStatus: string; onNavigate: (v: string) => void; onRefresh: () => void }) {
  return <>
    <div className="stats">{[['Total leads', stats.total_leads], ['Hot leads', stats.hot_leads], ['Qualified buyers', stats.buyers], ['Calls logged', stats.calls]].map(([label, value]) => <article key={String(label)}><span>{label}</span><strong>{value}</strong></article>)}</div>
    <div className="sectionTitle"><h2>Priority Leads</h2><button className="secondary" onClick={onRefresh}>Refresh data</button></div>
    <div className="tableWrap"><table><thead><tr><th>Seller</th><th>Property</th><th>ZIP</th><th>Motivation</th><th>Distress</th><th>MAO</th></tr></thead><tbody>{leads.length ? leads.slice(0, 8).map(l => <tr key={l.id}><td>{l.seller_name}</td><td>{l.address}</td><td>{l.zip_code}</td><td>{l.motivation_score}</td><td>{l.distress_score}</td><td>{money(l.mao)}</td></tr>) : <tr><td colSpan={6}>No leads found. API status: {apiStatus}.</td></tr>}</tbody></table></div>
    <div className="grid modules">{[['Leads','Create and score seller opportunities.'],['Cash Buyers','Build verified investor buy boxes.'],['Underwriting','Calculate MAO and assignment spread.'],['Buyer Matching','Rank buyers by fit and reliability.'],['Bland Calls','Log inbound and outbound call events.'],['Driving for Dollars','Capture distressed property observations.']].map(([title, description], index) => <button className="module" key={title} onClick={() => onNavigate(title)}><div className="number">0{index + 1}</div><h3>{title}</h3><p>{description}</p><span>Open module →</span></button>)}</div>
  </>;
}

function Field({ label, name, type = 'text', required = false, defaultValue, placeholder }: any) { return <label><span>{label}</span><input name={name} type={type} required={required} defaultValue={defaultValue} placeholder={placeholder} /></label>; }

function LeadsPanel({ leads, onSubmit, loading }: any) { return <div className="twoCol"><form className="card form" onSubmit={onSubmit}><h2>Create Lead</h2><div className="formGrid"><Field label="Seller name" name="seller_name" required/><Field label="Phone" name="phone" required/><Field label="Email" name="email" type="email"/><Field label="Address" name="address" required/><Field label="City" name="city" required/><Field label="State" name="state" required defaultValue="FL"/><Field label="ZIP" name="zip_code" required/><Field label="Beds" name="bedrooms" type="number" defaultValue="3"/><Field label="Baths" name="bathrooms" type="number" defaultValue="2"/><Field label="Sqft" name="sqft" type="number" defaultValue="1500"/><Field label="Asking price" name="asking_price" type="number"/><Field label="ARV" name="arv" type="number" required/><Field label="Repairs" name="repairs" type="number" required/><Field label="Motivation 0-100" name="motivation_score" type="number" defaultValue="70"/><Field label="Equity 0-100" name="equity_score" type="number" defaultValue="70"/><Field label="Timeline days" name="timeline_days" type="number" defaultValue="30"/></div><label><span>Distress signals, comma-separated</span><textarea name="distress_signals" defaultValue="vacant, inherited_property"/></label><label><span>Notes</span><textarea name="notes"/></label><button className="primary" disabled={loading}>{loading ? 'Saving…' : 'Create lead'}</button></form><div className="card"><h2>Live Leads</h2><div className="tableWrap compact"><table><tbody>{leads.map((l: Lead) => <tr key={l.id}><td><strong>{l.seller_name}</strong><small>{l.address}</small></td><td>{money(l.mao)}</td></tr>)}</tbody></table></div></div></div>; }

function BuyerPanel({ onSubmit, loading }: any) { return <form className="card form narrow" onSubmit={onSubmit}><h2>Add Cash Buyer</h2><div className="formGrid"><Field label="Buyer name" name="name" required/><Field label="Company" name="company"/><Field label="Buyer type" name="buyer_type" defaultValue="fix_and_flip"/><Field label="Phone" name="phone" required/><Field label="Email" name="email" type="email"/><Field label="ZIP codes" name="zip_codes" placeholder="33101, 33125"/><Field label="Minimum price" name="min_price" type="number" defaultValue="50000"/><Field label="Maximum price" name="max_price" type="number" defaultValue="300000"/><Field label="Maximum rehab" name="max_rehab" type="number" defaultValue="75000"/><Field label="Closing days" name="closing_days" type="number" defaultValue="10"/><Field label="Response rate" name="response_rate" type="number" defaultValue="80"/><Field label="Reliability score" name="reliability_score" type="number" defaultValue="85"/></div><label className="check"><input name="proof_of_funds_verified" type="checkbox"/><span>Proof of funds verified</span></label><button className="primary" disabled={loading}>Save buyer</button></form>; }

function UnderwritePanel({ onSubmit, loading, result }: any) { return <div className="twoCol"><form className="card form" onSubmit={onSubmit}><h2>Residential Underwriting</h2><div className="formGrid"><Field label="ARV" name="arv" type="number" defaultValue="250000" required/><Field label="Repairs" name="repairs" type="number" defaultValue="50000" required/><Field label="Assignment fee" name="assignment_fee" type="number" defaultValue="15000" required/><Field label="MAO factor" name="mao_factor" type="number" defaultValue="0.70" required/></div><button className="primary" disabled={loading}>Calculate MAO</button></form><div className="card result"><span>Maximum Allowable Offer</span><strong>{result ? money(result.mao) : 'Run calculation'}</strong><p>Formula: ARV × factor − repairs − assignment fee.</p></div></div>; }

function MatchPanel({ propertyId, setPropertyId, onMatch, matches, loading }: any) { return <div className="card"><div className="inline"><div><h2>Predictive Buyer Matching</h2><p>Enter a property ID and rank compatible buyers.</p></div><div className="matchControls"><input value={propertyId} onChange={e => setPropertyId(e.target.value)} type="number"/><button className="primary" onClick={onMatch} disabled={loading}>Run match</button></div></div><div className="matchList">{matches.map((m: Match) => <article key={m.buyer_id}><div><h3>{m.buyer_name}</h3><p>{m.reasons.join(' · ')}</p></div><strong>{m.score}/100</strong></article>)}</div></div>; }

function BlandPanel({ onSubmit, loading }: any) { return <form className="card form narrow" onSubmit={onSubmit}><h2>Test Bland.ai Webhook</h2><div className="formGrid"><Field label="Call ID" name="call_id" defaultValue={`test-${Date.now()}`} required/><Field label="Direction" name="direction" defaultValue="inbound"/><Field label="Status" name="status" defaultValue="completed"/></div><label><span>Summary</span><textarea name="summary" defaultValue="Qualified motivated seller"/></label><button className="primary" disabled={loading}>Submit call event</button></form>; }

function DrivingPanel({ onSubmit, loading }: any) { return <form className="card form narrow" onSubmit={onSubmit}><h2>Driving for Dollars Intake</h2><div className="formGrid"><Field label="Observer / seller" name="seller_name" defaultValue="Unknown owner" required/><Field label="Contact phone" name="phone" defaultValue="0000000000" required/><Field label="Address" name="address" required/><Field label="City" name="city" required/><Field label="State" name="state" defaultValue="FL" required/><Field label="ZIP" name="zip_code" required/><Field label="Latitude" name="latitude" type="number"/><Field label="Longitude" name="longitude" type="number"/><Field label="Estimated ARV" name="arv" type="number" defaultValue="200000" required/><Field label="Estimated repairs" name="repairs" type="number" defaultValue="60000" required/><Field label="Motivation" name="motivation_score" type="number" defaultValue="50"/><Field label="Equity" name="equity_score" type="number" defaultValue="60"/></div><input type="hidden" name="bedrooms" value="3"/><input type="hidden" name="bathrooms" value="2"/><input type="hidden" name="sqft" value="1200"/><input type="hidden" name="timeline_days" value="30"/><label><span>Visible distress indicators</span><textarea name="distress_signals" defaultValue="overgrown_grass, boarded_windows"/></label><button className="primary" disabled={loading}>Create D4D lead</button></form>; }

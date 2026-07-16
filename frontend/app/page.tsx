'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://backend-pi-opal-65.vercel.app';

type Stats = { total_leads: number; hot_leads: number; buyers: number; calls: number; queued_tasks?: number; completed_tasks?: number; pending_approvals?: number; campaigns?: number; autonomy_mode?: string };
type Lead = { id: number; property_id?: number; seller_name: string; phone: string; status: string; distress_score: number; motivation_score: number; address?: string; zip_code?: string; mao?: number };
type Match = { buyer_id: number; buyer_name: string; score: number; reasons: string[] };
type Task = { id: number; type: string; status: string; priority: number; lead_id?: number; result?: Record<string, unknown>; error?: string };
type Approval = { id: number; action_type: string; status: string; summary: string; entity_type: string; entity_id: number };
type Agent = { name: string; role: string; status: string };
type Campaign = { id: number; name: string; type: string; status: string; audience_count: number; sent_count: number; response_count: number };
type AutonomyStatus = { mode: string; agents: Agent[]; tasks: Task[]; approvals: Approval[]; campaigns: Campaign[] };
type Notice = { kind: 'success' | 'error'; text: string } | null;
type View = 'Command Center' | 'Autonomous Ops' | 'Leads' | 'Cash Buyers' | 'Underwriting' | 'Buyer Matching' | 'Bland Calls' | 'Driving for Dollars';

const navItems: View[] = ['Command Center', 'Autonomous Ops', 'Leads', 'Cash Buyers', 'Underwriting', 'Buyer Matching', 'Bland Calls', 'Driving for Dollars'];

function money(value?: number) {
  if (value === undefined || value === null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

function Field({ label, name, type = 'text', required = false, defaultValue, placeholder }: { label: string; name: string; type?: string; required?: boolean; defaultValue?: string; placeholder?: string }) {
  return <label><span>{label}</span><input name={name} type={type} required={required} defaultValue={defaultValue} placeholder={placeholder} /></label>;
}

export default function Home() {
  const [active, setActive] = useState<View>('Command Center');
  const [stats, setStats] = useState<Stats>({ total_leads: 0, hot_leads: 0, buyers: 0, calls: 0 });
  const [leads, setLeads] = useState<Lead[]>([]);
  const [autonomy, setAutonomy] = useState<AutonomyStatus>({ mode: 'checking', agents: [], tasks: [], approvals: [], campaigns: [] });
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'offline'>('checking');
  const [notice, setNotice] = useState<Notice>(null);
  const [loading, setLoading] = useState(false);
  const [matches, setMatches] = useState<Match[]>([]);
  const [matchPropertyId, setMatchPropertyId] = useState('1');
  const [underwriteResult, setUnderwriteResult] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [dashboardResponse, leadsResponse, autonomyResponse] = await Promise.all([
        fetch(`${API_URL}/dashboard`, { cache: 'no-store' }),
        fetch(`${API_URL}/leads`, { cache: 'no-store' }),
        fetch(`${API_URL}/autonomy/status`, { cache: 'no-store' }),
      ]);
      if (!dashboardResponse.ok || !leadsResponse.ok || !autonomyResponse.ok) throw new Error('API request failed');
      setStats(await dashboardResponse.json());
      setLeads(await leadsResponse.json());
      setAutonomy(await autonomyResponse.json());
      setApiStatus('connected');
    } catch {
      setApiStatus('offline');
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function post(path: string, body: unknown) {
    setLoading(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : 'Request failed');
      setNotice({ kind: 'success', text: 'Operation completed successfully.' });
      await refresh();
      return data;
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Request failed' });
      throw error;
    } finally { setLoading(false); }
  }

  async function createLead(event: FormEvent<HTMLFormElement>, source = 'manual') {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    await post(source === 'driving_for_dollars' ? '/driving-for-dollars' : '/leads', {
      seller_name: form.get('seller_name'), phone: form.get('phone'), email: form.get('email') || null, source,
      motivation_score: Number(form.get('motivation_score') || 0), equity_score: Number(form.get('equity_score') || 0), timeline_days: Number(form.get('timeline_days') || 30), notes: form.get('notes') || null,
      property: { address: form.get('address'), city: form.get('city'), state: form.get('state'), zip_code: form.get('zip_code'), property_type: 'single_family', bedrooms: Number(form.get('bedrooms') || 0), bathrooms: Number(form.get('bathrooms') || 0), sqft: Number(form.get('sqft') || 0), asking_price: Number(form.get('asking_price') || 0), arv: Number(form.get('arv') || 0), repairs: Number(form.get('repairs') || 0), distress_signals: String(form.get('distress_signals') || '').split(',').map(value => value.trim()).filter(Boolean), latitude: form.get('latitude') ? Number(form.get('latitude')) : null, longitude: form.get('longitude') ? Number(form.get('longitude')) : null },
    });
    formElement.reset();
  }

  async function createBuyer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    await post('/buyers', { name: form.get('name'), company: form.get('company') || null, buyer_type: form.get('buyer_type'), phone: form.get('phone'), email: form.get('email') || null, zip_codes: String(form.get('zip_codes') || '').split(',').map(value => value.trim()).filter(Boolean), asset_types: ['single_family'], min_price: Number(form.get('min_price') || 0), max_price: Number(form.get('max_price') || 10000000), max_rehab: Number(form.get('max_rehab') || 500000), closing_days: Number(form.get('closing_days') || 14), proof_of_funds_verified: form.get('proof_of_funds_verified') === 'on', response_rate: Number(form.get('response_rate') || 0), reliability_score: Number(form.get('reliability_score') || 50) });
    formElement.reset();
  }

  async function underwrite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const data = await post('/underwrite', { arv: Number(form.get('arv')), repairs: Number(form.get('repairs')), assignment_fee: Number(form.get('assignment_fee')), mao_factor: Number(form.get('mao_factor')) });
    setUnderwriteResult(data.mao as number);
  }

  async function runMatch() {
    setLoading(true); setNotice(null);
    try {
      const response = await fetch(`${API_URL}/properties/${matchPropertyId}/matches`, { cache: 'no-store' });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Match failed'); setMatches(data);
    } catch (error) { setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Match failed' }); }
    finally { setLoading(false); }
  }

  async function testBland(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    await post('/webhooks/bland', { call_id: form.get('call_id'), direction: form.get('direction'), status: form.get('status'), summary: form.get('summary') });
  }

  return <main className="shell">
    <aside className="sidebar"><div className="brand">SAHJONY</div><p>Wholesale Operations</p><nav>{navItems.map(item => <button key={item} className={active === item ? 'active' : ''} onClick={() => setActive(item)}>{item}</button>)}</nav><div className={`apiBadge ${apiStatus}`}>API {apiStatus}</div></aside>
    <section className="workspace"><header className="topbar"><div><span className="eyebrow">AUTONOMOUS WORKFORCE</span><h1>{active}</h1><p>Supervised autonomous residential and commercial wholesale operations.</p></div><div className="toolbar"><button className="secondary" onClick={() => void refresh()}>Refresh</button><button className="primary" onClick={() => setActive('Leads')}>+ Add Lead</button></div></header>
      {notice && <div className={`notice ${notice.kind}`}>{notice.text}</div>}
      {active === 'Command Center' && <CommandCenter stats={stats} leads={leads} onNavigate={setActive} />}
      {active === 'Autonomous Ops' && <AutonomyPanel status={autonomy} loading={loading} runDaily={() => void post('/autonomy/run', { agent_name: 'executive-orchestrator', objective: 'Run daily wholesale operations' })} execute={() => void post('/autonomy/execute', { limit: 20 })} approve={(id, decision) => void post(`/approvals/${id}/decision`, { decision, decided_by: 'owner' })} createDisposition={(propertyId) => void post(`/autonomy/disposition/${propertyId}`, {})} />}
      {active === 'Leads' && <LeadsPanel leads={leads} onSubmit={event => void createLead(event)} loading={loading} />}
      {active === 'Cash Buyers' && <BuyerPanel onSubmit={event => void createBuyer(event)} loading={loading} />}
      {active === 'Underwriting' && <UnderwritePanel onSubmit={event => void underwrite(event)} loading={loading} result={underwriteResult} />}
      {active === 'Buyer Matching' && <MatchPanel propertyId={matchPropertyId} setPropertyId={setMatchPropertyId} onMatch={() => void runMatch()} matches={matches} loading={loading} />}
      {active === 'Bland Calls' && <BlandPanel onSubmit={event => void testBland(event)} loading={loading} />}
      {active === 'Driving for Dollars' && <DrivingPanel onSubmit={event => void createLead(event, 'driving_for_dollars')} loading={loading} />}
    </section>
  </main>;
}

function CommandCenter({ stats, leads, onNavigate }: { stats: Stats; leads: Lead[]; onNavigate: (view: View) => void }) {
  const cards = [['Total leads', stats.total_leads], ['Hot leads', stats.hot_leads], ['Buyers', stats.buyers], ['Calls', stats.calls], ['Queued tasks', stats.queued_tasks || 0], ['Pending approvals', stats.pending_approvals || 0], ['Campaigns', stats.campaigns || 0], ['Completed tasks', stats.completed_tasks || 0]];
  return <><div className="stats autonomyStats">{cards.map(([label, value]) => <article key={String(label)}><span>{label}</span><strong>{value}</strong></article>)}</div><div className="sectionTitle"><h2>Priority Leads</h2><button className="secondary" onClick={() => onNavigate('Autonomous Ops')}>Open autonomous control</button></div><div className="tableWrap"><table><thead><tr><th>Seller</th><th>Property</th><th>Status</th><th>Motivation</th><th>Distress</th><th>MAO</th></tr></thead><tbody>{leads.length ? leads.slice(0, 10).map(lead => <tr key={lead.id}><td>{lead.seller_name}</td><td>{lead.address}</td><td>{lead.status}</td><td>{lead.motivation_score}</td><td>{lead.distress_score}</td><td>{money(lead.mao)}</td></tr>) : <tr><td colSpan={6}>No leads found.</td></tr>}</tbody></table></div></>;
}

function AutonomyPanel({ status, loading, runDaily, execute, approve, createDisposition }: { status: AutonomyStatus; loading: boolean; runDaily: () => void; execute: () => void; approve: (id: number, decision: 'approved' | 'rejected') => void; createDisposition: (propertyId: number) => void }) {
  const [propertyId, setPropertyId] = useState('1');
  return <div className="autonomyLayout"><div className="card"><div className="inline"><div><h2>Executive Orchestrator</h2><p>Mode: {status.mode}</p></div><div className="toolbar"><button className="secondary" disabled={loading} onClick={runDaily}>Plan daily operations</button><button className="primary" disabled={loading} onClick={execute}>Execute queued tasks</button></div></div><div className="agentGrid">{status.agents.map(agent => <article key={agent.name}><span className="statusDot"/><div><strong>{agent.name}</strong><p>{agent.role}</p></div></article>)}</div></div><div className="twoCol"><div className="card"><h2>Task Queue</h2><div className="tableWrap compact"><table><thead><tr><th>ID</th><th>Task</th><th>Status</th><th>Priority</th></tr></thead><tbody>{status.tasks.map(task => <tr key={task.id}><td>{task.id}</td><td>{task.type}</td><td>{task.status}</td><td>{task.priority}</td></tr>)}</tbody></table></div></div><div className="card"><h2>Disposition Automation</h2><p>Create a buyer campaign from a property and route it through approval.</p><div className="matchControls"><input value={propertyId} onChange={event => setPropertyId(event.target.value)} type="number"/><button className="primary" disabled={loading} onClick={() => createDisposition(Number(propertyId))}>Create campaign</button></div><h3>Campaigns</h3>{status.campaigns.map(campaign => <div className="campaignRow" key={campaign.id}><span>{campaign.name}</span><strong>{campaign.status}</strong></div>)}</div></div><div className="card"><h2>Approval Center</h2>{status.approvals.length ? <div className="approvalList">{status.approvals.map(item => <article key={item.id}><div><strong>{item.action_type}</strong><p>{item.summary}</p></div><div className="toolbar"><button className="secondary" onClick={() => approve(item.id, 'rejected')}>Reject</button><button className="primary" onClick={() => approve(item.id, 'approved')}>Approve</button></div></article>)}</div> : <p>No pending approvals.</p>}</div></div>;
}

function LeadsPanel({ leads, onSubmit, loading }: { leads: Lead[]; onSubmit: (event: FormEvent<HTMLFormElement>) => void; loading: boolean }) { return <div className="twoCol"><form className="card form" onSubmit={onSubmit}><h2>Create Lead</h2><div className="formGrid"><Field label="Seller name" name="seller_name" required/><Field label="Phone" name="phone" required/><Field label="Email" name="email" type="email"/><Field label="Address" name="address" required/><Field label="City" name="city" required/><Field label="State" name="state" required defaultValue="FL"/><Field label="ZIP" name="zip_code" required/><Field label="Beds" name="bedrooms" type="number" defaultValue="3"/><Field label="Baths" name="bathrooms" type="number" defaultValue="2"/><Field label="Sqft" name="sqft" type="number" defaultValue="1500"/><Field label="Asking price" name="asking_price" type="number"/><Field label="ARV" name="arv" type="number" required/><Field label="Repairs" name="repairs" type="number" required/><Field label="Motivation" name="motivation_score" type="number" defaultValue="70"/><Field label="Equity" name="equity_score" type="number" defaultValue="70"/><Field label="Timeline days" name="timeline_days" type="number" defaultValue="30"/></div><label><span>Distress signals</span><textarea name="distress_signals" defaultValue="vacant, inherited_property"/></label><label><span>Notes</span><textarea name="notes"/></label><button className="primary" disabled={loading}>Create and auto-score lead</button></form><div className="card"><h2>Live Leads</h2><div className="tableWrap compact"><table><tbody>{leads.map(lead => <tr key={lead.id}><td><strong>{lead.seller_name}</strong><small>{lead.address}</small></td><td>{lead.status}</td><td>{money(lead.mao)}</td></tr>)}</tbody></table></div></div></div>; }

function BuyerPanel({ onSubmit, loading }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; loading: boolean }) { return <form className="card form narrow" onSubmit={onSubmit}><h2>Add Cash Buyer</h2><div className="formGrid"><Field label="Buyer name" name="name" required/><Field label="Company" name="company"/><Field label="Buyer type" name="buyer_type" defaultValue="fix_and_flip"/><Field label="Phone" name="phone" required/><Field label="Email" name="email" type="email"/><Field label="ZIP codes" name="zip_codes" placeholder="33101, 33125"/><Field label="Minimum price" name="min_price" type="number" defaultValue="50000"/><Field label="Maximum price" name="max_price" type="number" defaultValue="300000"/><Field label="Maximum rehab" name="max_rehab" type="number" defaultValue="75000"/><Field label="Closing days" name="closing_days" type="number" defaultValue="10"/><Field label="Response rate" name="response_rate" type="number" defaultValue="80"/><Field label="Reliability score" name="reliability_score" type="number" defaultValue="85"/></div><label className="check"><input name="proof_of_funds_verified" type="checkbox"/><span>Proof of funds verified</span></label><button className="primary" disabled={loading}>Save buyer</button></form>; }

function UnderwritePanel({ onSubmit, loading, result }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; loading: boolean; result: number | null }) { return <div className="twoCol"><form className="card form" onSubmit={onSubmit}><h2>Residential Underwriting</h2><div className="formGrid"><Field label="ARV" name="arv" type="number" defaultValue="250000" required/><Field label="Repairs" name="repairs" type="number" defaultValue="50000" required/><Field label="Assignment fee" name="assignment_fee" type="number" defaultValue="15000" required/><Field label="MAO factor" name="mao_factor" type="number" defaultValue="0.70" required/></div><button className="primary" disabled={loading}>Calculate MAO</button></form><div className="card result"><span>Maximum Allowable Offer</span><strong>{result === null ? 'Run calculation' : money(result)}</strong></div></div>; }

function MatchPanel({ propertyId, setPropertyId, onMatch, matches, loading }: { propertyId: string; setPropertyId: (value: string) => void; onMatch: () => void; matches: Match[]; loading: boolean }) { return <div className="card"><div className="inline"><div><h2>Predictive Buyer Matching</h2><p>Rank compatible buyers by buy box and reliability.</p></div><div className="matchControls"><input value={propertyId} onChange={event => setPropertyId(event.target.value)} type="number"/><button className="primary" onClick={onMatch} disabled={loading}>Run match</button></div></div><div className="matchList">{matches.map(match => <article key={match.buyer_id}><div><h3>{match.buyer_name}</h3><p>{match.reasons.join(' · ')}</p></div><strong>{match.score}/100</strong></article>)}</div></div>; }

function BlandPanel({ onSubmit, loading }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; loading: boolean }) { return <form className="card form narrow" onSubmit={onSubmit}><h2>Test Bland.ai Webhook</h2><div className="formGrid"><Field label="Call ID" name="call_id" defaultValue="test-call" required/><Field label="Direction" name="direction" defaultValue="inbound"/><Field label="Status" name="status" defaultValue="completed"/></div><label><span>Summary</span><textarea name="summary" defaultValue="Qualified motivated seller"/></label><button className="primary" disabled={loading}>Submit call event</button></form>; }

function DrivingPanel({ onSubmit, loading }: { onSubmit: (event: FormEvent<HTMLFormElement>) => void; loading: boolean }) { return <form className="card form narrow" onSubmit={onSubmit}><h2>Driving for Dollars Intake</h2><div className="formGrid"><Field label="Observer / seller" name="seller_name" defaultValue="Unknown owner" required/><Field label="Contact phone" name="phone" defaultValue="0000000000" required/><Field label="Address" name="address" required/><Field label="City" name="city" required/><Field label="State" name="state" defaultValue="FL" required/><Field label="ZIP" name="zip_code" required/><Field label="Latitude" name="latitude" type="number"/><Field label="Longitude" name="longitude" type="number"/><Field label="Estimated ARV" name="arv" type="number" defaultValue="200000" required/><Field label="Estimated repairs" name="repairs" type="number" defaultValue="60000" required/><Field label="Motivation" name="motivation_score" type="number" defaultValue="50"/><Field label="Equity" name="equity_score" type="number" defaultValue="60"/></div><input type="hidden" name="bedrooms" value="3"/><input type="hidden" name="bathrooms" value="2"/><input type="hidden" name="sqft" value="1200"/><input type="hidden" name="timeline_days" value="30"/><label><span>Visible distress indicators</span><textarea name="distress_signals" defaultValue="overgrown_grass, boarded_windows"/></label><button className="primary" disabled={loading}>Create D4D lead</button></form>; }

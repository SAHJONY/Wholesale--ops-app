'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import styles from './owner.module.css';

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'https://backend-pi-opal-65.vercel.app').replace(/\/$/, '');
const SESSION_STORAGE = 'sahjony_owner_session';
const OWNER_EMAIL = 'sahjonycapitalllc@outlook.com';
const REQUEST_TIMEOUT_MS = 15000;

type Principal = { organization_id: number; organization_name: string; user_id: number; email: string; name: string; role: string };
type Pipeline = { total_leads: number; active_deals: number; projected_assignment_revenue: number; stages: Array<{ stage: string; count: number }> };
type Lead = { id: number; seller_name: string; phone: string; status: string; address?: string; city?: string; state?: string; mao?: number };
type FollowUp = { id: number; title: string; status: string; priority: number; due_at?: string; lead_id?: number };
type TeamMember = { user_id: number; name: string; email: string; role: string; active: boolean };
type AuthMode = 'login' | 'request-reset' | 'reset-password';
type ApiState = 'checking' | 'online' | 'offline';
type CommandCenter = {
  generated_at: string;
  mode: string;
  kpis: { total_leads: number; hot_leads: number; active_deals: number; qualified_buyers: number; projected_assignment_revenue: number; probability_weighted_revenue: number; queued_tasks: number; failed_tasks: number; pending_approvals: number };
  priority_leads: Array<{ lead_id: number; seller_name: string; status: string; source: string; score: number; priority: number; timeline_days?: number }>;
  deal_risk: Array<{ deal_id: number; stage: string; risk_score: number; probability_to_close: number; projected_assignment_fee: number; next_action?: string; property: { city?: string; state?: string; zip_code?: string } }>;
  agent_health: Array<{ name: string; role: string; status: string; health: string; last_run_at?: string; last_status?: string; confidence?: number }>;
  queue: Array<{ id: number; task_type: string; priority: number; status: string; lead_id?: number; created_at: string }>;
  approvals: Array<{ id: number; action_type: string; summary: string; entity_type: string; entity_id: number; created_at: string }>;
};

function money(value: number) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0); }
function formatDate(value?: string) { return value ? new Date(value).toLocaleString() : 'Never'; }
function safeReturnPath() {
  if (typeof window === 'undefined') return '';
  const value = new URLSearchParams(window.location.search).get('returnTo') || '';
  return value.startsWith('/owner/') && !value.startsWith('//') ? value : '';
}

async function fetchJson(path: string, options: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_URL}${path}`, { ...options, cache: 'no-store', signal: controller.signal });
    const text = await response.text();
    let data: any = {};
    if (text) {
      try { data = JSON.parse(text); }
      catch { throw new Error(`Backend returned an unreadable response (HTTP ${response.status}).`); }
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : typeof data.message === 'string' ? data.message : 'Request failed';
      throw new Error(`${detail} (HTTP ${response.status})`);
    }
    return data;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('The backend did not respond within 15 seconds.');
    if (error instanceof TypeError) throw new Error(`Cannot connect to the backend at ${API_URL}.`);
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export default function OwnerWorkspace() {
  const [sessionToken, setSessionToken] = useState('');
  const [email, setEmail] = useState(OWNER_EMAIL);
  const [password, setPassword] = useState('');
  const [resetCode, setResetCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [authMode, setAuthMode] = useState<AuthMode>('login');
  const [apiState, setApiState] = useState<ApiState>('checking');
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [commandCenter, setCommandCenter] = useState<CommandCenter | null>(null);
  const [lastCycle, setLastCycle] = useState<{ executed: number; completed: number; failed: number } | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [cycleRunning, setCycleRunning] = useState(false);

  const request = useCallback(async (path: string, options: RequestInit = {}, tokenOverride?: string) => {
    const token = (tokenOverride ?? sessionToken).trim();
    return fetchJson(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
    });
  }, [sessionToken]);

  const checkApi = useCallback(async () => {
    setApiState('checking');
    try { await fetchJson('/health'); setApiState('online'); }
    catch (err) { setApiState('offline'); setError(err instanceof Error ? err.message : 'Backend unavailable'); }
  }, []);

  const loadWorkspace = useCallback(async (tokenOverride?: string) => {
    const token = (tokenOverride ?? sessionToken).trim();
    if (!token) return false;
    setLoading(true); setError('');
    try {
      const [me, pipelineData, leadData, followUpData, teamData, executiveData] = await Promise.all([
        request('/auth/me', {}, token), request('/crm/pipeline', {}, token), request('/crm/leads', {}, token), request('/crm/follow-ups', {}, token), request('/auth/team', {}, token), request('/executive/command-center', {}, token),
      ]);
      window.localStorage.setItem(SESSION_STORAGE, token);
      setSessionToken(token); setPrincipal(me); setPipeline(pipelineData); setLeads(leadData); setFollowUps(followUpData); setTeam(teamData); setCommandCenter(executiveData);
      return true;
    } catch (err) {
      window.localStorage.removeItem(SESSION_STORAGE); setSessionToken(''); setPrincipal(null); setError(err instanceof Error ? err.message : 'Unable to load workspace');
      return false;
    } finally { setLoading(false); }
  }, [request, sessionToken]);

  useEffect(() => {
    void checkApi();
    const stored = window.localStorage.getItem(SESSION_STORAGE) || '';
    if (stored) void loadWorkspace(stored);
  }, [checkApi, loadWorkspace]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError(''); setNotice('');
    try {
      const data = await fetchJson('/human-auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      const token = String(data.access_token || '');
      if (!token) throw new Error('Login succeeded but no session token was returned.');
      setPassword('');
      const loaded = await loadWorkspace(token);
      const returnTo = safeReturnPath();
      if (loaded && returnTo) window.location.replace(returnTo);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to sign in';
      setError(message);
      if (/invalid email or password|not configured|temporarily locked/i.test(message)) setNotice('Use Forgot password below to create a fresh owner password and clear any account lock.');
    } finally { setLoading(false); }
  }

  async function requestReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError(''); setNotice('');
    try {
      const data = await fetchJson('/human-auth/request-password-reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email.trim().toLowerCase() }) });
      setNotice(data.message || 'Reset code sent. Check your email.'); setAuthMode('reset-password');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to send reset code'); }
    finally { setLoading(false); }
  }

  async function resetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError(''); setNotice('');
    try {
      await fetchJson('/human-auth/reset-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email.trim().toLowerCase(), code: resetCode.trim(), password: newPassword }) });
      setPassword(newPassword); setNewPassword(''); setResetCode(''); setNotice('Password updated. Click Sign in using the new password.'); setAuthMode('login');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to reset password'); }
    finally { setLoading(false); }
  }

  async function runAutonomousCycle() {
    setCycleRunning(true); setError(''); setNotice('');
    try { const result = await request('/executive/run-cycle', { method: 'POST', body: JSON.stringify({ execute_limit: 25 }) }); setLastCycle({ executed: result.executed || 0, completed: result.completed || 0, failed: result.failed || 0 }); setNotice(`Autonomous cycle finished: ${result.completed || 0} completed, ${result.failed || 0} failed.`); await loadWorkspace(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Autonomous cycle failed'); }
    finally { setCycleRunning(false); }
  }

  async function decideApproval(id: number, decision: 'approved' | 'rejected') {
    setLoading(true); setError('');
    try { await request(`/workspace/approvals/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) }); setNotice(`Approval ${decision}.`); await loadWorkspace(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to record decision'); }
    finally { setLoading(false); }
  }

  async function importExisting() {
    setLoading(true); setError('');
    try { const result = await request('/crm/import-existing', { method: 'POST', body: '{}' }); setNotice(`Imported ${result.linked_leads} leads and ${result.linked_deals} deals.`); await loadWorkspace(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Import failed'); }
    finally { setLoading(false); }
  }

  async function addTeamMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); setLoading(true);
    try { await request('/auth/team', { method: 'POST', body: JSON.stringify({ name: form.get('name'), email: form.get('email'), role: form.get('role') }) }); formElement.reset(); setNotice('Team member added.'); await loadWorkspace(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to add team member'); }
    finally { setLoading(false); }
  }

  function signOut() {
    const token = sessionToken; window.localStorage.removeItem(SESSION_STORAGE); setSessionToken(''); setPrincipal(null); setPipeline(null); setCommandCenter(null); setLeads([]); setFollowUps([]); setTeam([]); setError(''); setNotice('');
    if (token) void fetch(`${API_URL}/human-auth/logout`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }).catch(() => undefined);
  }

  if (!principal) return <main className={styles.setup}><section className={styles.setupCard}>
    <span className={styles.eyebrow}>SAHJONY WHOLESALE OS</span>
    <h1>{authMode === 'login' ? 'Owner Sign In' : authMode === 'request-reset' ? 'Forgot Password' : 'Reset Password'}</h1>
    <p>{authMode === 'login' ? (safeReturnPath() ? 'Sign in to continue to the requested owner workspace.' : 'Sign in from any phone or computer.') : authMode === 'request-reset' ? 'We will email you a six-digit reset code.' : 'Enter the code from your email and choose a new password.'}</p>
    <small>API: {API_URL}</small>
    <div className={apiState === 'online' ? styles.notice : apiState === 'offline' ? styles.error : styles.cycleSummary}>Backend: {apiState === 'checking' ? 'Checking…' : apiState === 'online' ? 'Online' : 'Offline'} {apiState === 'offline' && <button type="button" onClick={() => void checkApi()}>Retry connection</button>}</div>
    {notice && <div className={styles.notice}>{notice}</div>}{error && <div className={styles.error}>{error}</div>}
    {authMode === 'login' && <form onSubmit={signIn} className={styles.form}><label htmlFor="owner-email"><b>Email</b></label><input id="owner-email" value={email} onChange={e => setEmail(e.target.value)} type="email" autoComplete="email" required /><label htmlFor="owner-password"><b>Password</b></label><input id="owner-password" value={password} onChange={e => setPassword(e.target.value)} type="password" autoComplete="current-password" required /><button type="submit" disabled={loading || apiState !== 'online'}>{loading ? 'Signing in…' : 'Sign in'}</button><button type="button" className={styles.secondaryButton} onClick={() => { setError(''); setNotice(''); setAuthMode('request-reset'); }}>Forgot password?</button></form>}
    {authMode === 'request-reset' && <form onSubmit={requestReset} className={styles.form}><label htmlFor="reset-email"><b>Email</b></label><input id="reset-email" value={email} onChange={e => setEmail(e.target.value)} type="email" required /><button type="submit" disabled={loading || apiState !== 'online'}>{loading ? 'Sending…' : 'Send reset code'}</button><button type="button" className={styles.secondaryButton} onClick={() => setAuthMode('login')}>Back to sign in</button></form>}
    {authMode === 'reset-password' && <form onSubmit={resetPassword} className={styles.form}><label><b>Email</b></label><input value={email} onChange={e => setEmail(e.target.value)} type="email" required /><label><b>Six-digit code</b></label><input value={resetCode} onChange={e => setResetCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" required minLength={6} maxLength={6} /><label><b>New password</b></label><input value={newPassword} onChange={e => setNewPassword(e.target.value)} type="password" required minLength={12} /><button type="submit" disabled={loading || apiState !== 'online'}>{loading ? 'Updating…' : 'Reset password'}</button><button type="button" className={styles.secondaryButton} onClick={() => setAuthMode('request-reset')}>Request another code</button></form>}
  </section></main>;

  const kpis = commandCenter?.kpis;
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>OWNER CONTROL PLANE</span><h1>{principal.organization_name}</h1><p>{principal.name} · {principal.role} · {commandCenter?.mode?.replaceAll('_', ' ')}</p></div><div className={styles.actions}><button className={styles.runButton} onClick={runAutonomousCycle} disabled={cycleRunning || loading}>{cycleRunning ? 'Running cycle…' : 'Run Autonomous Cycle'}</button><button onClick={() => void loadWorkspace()} disabled={loading}>Refresh</button><button onClick={importExisting} disabled={loading}>Import existing</button><button onClick={signOut}>Sign out</button></div></header>
    {notice && <div className={styles.notice}>{notice}</div>}{error && <div className={styles.error}>{error}</div>}
    {lastCycle && <div className={styles.cycleSummary}>Last cycle: <b>{lastCycle.executed}</b> executed · <b>{lastCycle.completed}</b> completed · <b>{lastCycle.failed}</b> failed</div>}
    <section className={styles.metrics}><article><span>Total leads</span><strong>{kpis?.total_leads ?? pipeline?.total_leads ?? 0}</strong></article><article><span>Hot leads</span><strong>{kpis?.hot_leads || 0}</strong></article><article><span>Active deals</span><strong>{kpis?.active_deals ?? pipeline?.active_deals ?? 0}</strong></article><article><span>Qualified buyers</span><strong>{kpis?.qualified_buyers || 0}</strong></article><article><span>Projected revenue</span><strong>{money(kpis?.projected_assignment_revenue ?? pipeline?.projected_assignment_revenue ?? 0)}</strong></article><article><span>Weighted revenue</span><strong>{money(kpis?.probability_weighted_revenue || 0)}</strong></article><article><span>Queued tasks</span><strong>{kpis?.queued_tasks || 0}</strong></article><article><span>Pending approvals</span><strong>{kpis?.pending_approvals || 0}</strong></article></section>
    <section className={styles.grid}><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>ACQUISITIONS</span><h2>Priority seller opportunities</h2></div><small>Ranked by urgency and lead score</small></div><div className={styles.list}>{commandCenter?.priority_leads.length ? commandCenter.priority_leads.map(item => <div key={item.lead_id}><span><b>{item.seller_name}</b><small>{item.source} · {item.status} · {item.timeline_days ?? '—'} days</small></span><span className={styles.score}>P{item.priority} · {Math.round(item.score)}</span></div>) : <p>No prioritized leads yet.</p>}</div></article><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>RISK</span><h2>Deal risk queue</h2></div><small>Highest risk first</small></div><div className={styles.list}>{commandCenter?.deal_risk.length ? commandCenter.deal_risk.map(item => <div key={item.deal_id}><span><b>Deal #{item.deal_id} · {item.property.city || 'Unknown'}, {item.property.state || ''}</b><small>{item.stage} · {item.probability_to_close}% close probability · {money(item.projected_assignment_fee)}</small><small>{item.next_action}</small></span><span className={styles.risk}>Risk {Math.round(item.risk_score)}</span></div>) : <p>No active deal risks.</p>}</div></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>AI WORKFORCE</span><h2>Agent health</h2></div><small>Last command-center refresh: {formatDate(commandCenter?.generated_at)}</small></div><div className={styles.agentGrid}>{commandCenter?.agent_health.map(agent => <article key={agent.name} className={styles.agentCard}><div><b>{agent.name.replaceAll('-', ' ')}</b><span className={`${styles.health} ${styles[agent.health] || ''}`}>{agent.health}</span></div><p>{agent.role}</p><small>Last run: {formatDate(agent.last_run_at)}{agent.confidence != null ? ` · ${Math.round(agent.confidence * 100)}% confidence` : ''}</small></article>)}</div></section>
    <section className={styles.grid}><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>CONTROL GATE</span><h2>Pending approvals</h2></div><strong>{commandCenter?.approvals.length || 0}</strong></div><div className={styles.list}>{commandCenter?.approvals.length ? commandCenter.approvals.map(item => <div key={item.id}><span><b>{item.action_type.replaceAll('_', ' ')}</b><small>{item.summary}</small><small>{formatDate(item.created_at)}</small></span><span className={styles.decisionButtons}><button onClick={() => void decideApproval(item.id, 'approved')} disabled={loading}>Approve</button><button onClick={() => void decideApproval(item.id, 'rejected')} disabled={loading}>Reject</button></span></div>) : <p>No approvals waiting.</p>}</div></article><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>EXECUTION</span><h2>Autonomous queue</h2></div><strong>{commandCenter?.queue.length || 0}</strong></div><div className={styles.list}>{commandCenter?.queue.length ? commandCenter.queue.map(item => <div key={item.id}><span><b>{item.task_type.replaceAll('_', ' ')}</b><small>Task #{item.id} · Lead {item.lead_id || '—'} · {formatDate(item.created_at)}</small></span><span className={styles.score}>P{item.priority}</span></div>) : <p>No queued work.</p>}</div></article></section>
    <section className={styles.grid}><article className={styles.card}><h2>CRM Pipeline</h2><div className={styles.pipeline}>{pipeline?.stages.map(item => <div key={item.stage}><span>{item.stage.replaceAll('_', ' ')}</span><strong>{item.count}</strong></div>)}</div></article><article className={styles.card}><h2>Team</h2><div className={styles.list}>{team.map(member => <div key={member.user_id}><span><b>{member.name}</b><small>{member.email}</small></span><strong>{member.role}</strong></div>)}</div><form onSubmit={addTeamMember} className={styles.miniForm}><input name="name" placeholder="Name" required /><input name="email" type="email" placeholder="Email" required /><select name="role" defaultValue="acquisitions"><option value="acquisitions">Acquisitions</option><option value="disposition">Disposition</option><option value="transaction_coordinator">Transaction coordinator</option><option value="manager">Manager</option><option value="admin">Admin</option><option value="viewer">Viewer</option></select><button disabled={loading}>Add member</button></form></article></section>
    <section className={styles.grid}><article className={styles.card}><h2>Workspace Leads</h2><div className={styles.list}>{leads.length ? leads.map(lead => <div key={lead.id}><span><b>{lead.seller_name}</b><small>{lead.address}, {lead.city} {lead.state}</small></span><strong>{lead.status}</strong></div>) : <p>No tenant-scoped leads yet. Use Import existing.</p>}</div></article><article className={styles.card}><h2>Follow-ups</h2><div className={styles.list}>{followUps.length ? followUps.map(task => <div key={task.id}><span><b>{task.title}</b><small>Priority {task.priority}{task.due_at ? ` · ${new Date(task.due_at).toLocaleString()}` : ''}</small></span><strong>{task.status}</strong></div>) : <p>No follow-ups queued.</p>}</div></article></section>
  </main>;
}

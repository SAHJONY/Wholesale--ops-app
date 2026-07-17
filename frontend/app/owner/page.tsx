'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import styles from './owner.module.css';

const API_URL = 'https://backend-pi-opal-65.vercel.app';
const KEY_STORAGE = 'sahjony_owner_api_key';

type Principal = { organization_id: number; organization_name: string; user_id: number; email: string; name: string; role: string };
type Pipeline = { total_leads: number; active_deals: number; projected_assignment_revenue: number; stages: Array<{ stage: string; count: number }> };
type Lead = { id: number; seller_name: string; phone: string; status: string; address?: string; city?: string; state?: string; mao?: number };
type FollowUp = { id: number; title: string; status: string; priority: number; due_at?: string; lead_id?: number };
type TeamMember = { user_id: number; name: string; email: string; role: string; active: boolean };

function money(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);
}

function normalizeKey(value: string) {
  return value.trim().replace(/^['"]|['"]$/g, '');
}

export default function OwnerWorkspace() {
  const [apiKey, setApiKey] = useState('');
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = useCallback(async (path: string, options: RequestInit = {}, keyOverride?: string) => {
    const key = normalizeKey(keyOverride ?? apiKey);
    let response: Response;
    try {
      response = await fetch(`${API_URL}${path}`, {
        ...options,
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
          ...(key ? { 'X-API-Key': key } : {}),
          ...(options.headers || {}),
        },
      });
    } catch {
      throw new Error(`Cannot reach the backend API at ${API_URL}`);
    }
    let data: any = {};
    try {
      data = await response.json();
    } catch {
      throw new Error(`Backend returned an invalid response (${response.status})`);
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, [apiKey]);

  const loadWorkspace = useCallback(async (keyOverride?: string) => {
    const key = normalizeKey(keyOverride ?? apiKey);
    if (!key) return;
    setLoading(true);
    setError('');
    try {
      const [me, pipelineData, leadData, followUpData, teamData] = await Promise.all([
        request('/auth/me', {}, key),
        request('/crm/pipeline', {}, key),
        request('/crm/leads', {}, key),
        request('/crm/follow-ups', {}, key),
        request('/auth/team', {}, key),
      ]);
      window.localStorage.setItem(KEY_STORAGE, key);
      setApiKey(key);
      setPrincipal(me);
      setPipeline(pipelineData);
      setLeads(leadData);
      setFollowUps(followUpData);
      setTeam(teamData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load workspace');
      setPrincipal(null);
    } finally {
      setLoading(false);
    }
  }, [apiKey, request]);

  useEffect(() => {
    const stored = window.localStorage.getItem(KEY_STORAGE) || '';
    setApiKey(stored);
    if (stored) void loadWorkspace(stored);
  }, [loadWorkspace]);

  async function humanLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${API_URL}/human-auth/login`, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: loginEmail.trim().toLowerCase(), password: loginPassword }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Login failed');
      const token = String(data.access_token || '');
      if (!token) throw new Error('Login did not return a session token');
      setLoginPassword('');
      setNotice('Signed in successfully.');
      await loadWorkspace(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in');
    } finally {
      setLoading(false);
    }
  }

  async function pasteKey() {
    setError('');
    try {
      const value = await navigator.clipboard.readText();
      const key = normalizeKey(value);
      if (!key) throw new Error('Clipboard is empty.');
      setApiKey(key);
      setNotice('API key pasted. Tap Connect workspace.');
    } catch {
      setError('Clipboard access was blocked. Press and hold inside the key box, then choose Paste.');
    }
  }

  async function importExisting() {
    setLoading(true);
    setError('');
    try {
      const result = await request('/crm/import-existing', { method: 'POST', body: '{}' });
      setNotice(`Imported ${result.linked_leads} leads and ${result.linked_deals} deals.`);
      await loadWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setLoading(false);
    }
  }

  async function addTeamMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setLoading(true);
    try {
      await request('/auth/team', {
        method: 'POST',
        body: JSON.stringify({ name: form.get('name'), email: form.get('email'), role: form.get('role') }),
      });
      formElement.reset();
      setNotice('Team member added.');
      await loadWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to add team member');
    } finally {
      setLoading(false);
    }
  }

  function disconnect() {
    const token = apiKey;
    window.localStorage.removeItem(KEY_STORAGE);
    setApiKey('');
    setPrincipal(null);
    setPipeline(null);
    setLeads([]);
    setFollowUps([]);
    setTeam([]);
    setError('');
    setNotice('');
    if (token) void fetch(`${API_URL}/human-auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }).catch(() => undefined);
  }

  if (!principal) {
    return <main className={styles.setup}>
      <section className={styles.setupCard}>
        <span className={styles.eyebrow}>SAHJONY WHOLESALE OS</span>
        <h1>Owner Sign In</h1>
        <p>Sign in with your owner email and password from any phone or computer.</p>
        <small>API: {API_URL}</small>
        {notice && <div className={styles.notice}>{notice}</div>}
        {error && <div className={styles.error}>{error}</div>}

        <form onSubmit={humanLogin} className={styles.form}>
          <label htmlFor="owner-email"><b>Email</b></label>
          <input id="owner-email" value={loginEmail} onChange={(event) => setLoginEmail(event.target.value)} type="email" autoComplete="email" required placeholder="owner@company.com" />
          <label htmlFor="owner-password"><b>Password</b></label>
          <input id="owner-password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} type="password" autoComplete="current-password" required minLength={12} placeholder="Your secure password" />
          <button disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
        </form>

        <button type="button" className={styles.secondaryButton} onClick={() => setShowAdvanced(!showAdvanced)}>
          {showAdvanced ? 'Hide integration key login' : 'Use an API key instead'}
        </button>

        {showAdvanced && <form onSubmit={(event) => { event.preventDefault(); void loadWorkspace(apiKey); }} className={styles.form}>
          <label htmlFor="owner-api-key"><b>Owner API key</b></label>
          <textarea id="owner-api-key" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste the complete sahjony_live_... key here" rows={4} autoCapitalize="none" autoCorrect="off" spellCheck={false} />
          <small>{apiKey.length ? `${apiKey.length} characters entered` : 'No key entered yet'}</small>
          <button type="button" onClick={() => void pasteKey()} disabled={loading}>Paste key</button>
          <button type="submit" disabled={loading || !apiKey.trim()}>{loading ? 'Connecting…' : 'Connect workspace'}</button>
        </form>}
      </section>
    </main>;
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>OWNER CONTROL PLANE</span><h1>{principal.organization_name}</h1><p>{principal.name} · {principal.role}</p></div>
      <div className={styles.actions}><button onClick={() => void loadWorkspace()} disabled={loading}>Refresh</button><button onClick={importExisting} disabled={loading}>Import existing</button><button onClick={disconnect}>Sign out</button></div>
    </header>
    {notice && <div className={styles.notice}>{notice}</div>}
    {error && <div className={styles.error}>{error}</div>}
    <section className={styles.metrics}>
      <article><span>Workspace leads</span><strong>{pipeline?.total_leads || 0}</strong></article>
      <article><span>Active deals</span><strong>{pipeline?.active_deals || 0}</strong></article>
      <article><span>Projected revenue</span><strong>{money(pipeline?.projected_assignment_revenue || 0)}</strong></article>
      <article><span>Open follow-ups</span><strong>{followUps.filter(item => item.status !== 'completed').length}</strong></article>
    </section>
    <section className={styles.grid}>
      <article className={styles.card}><h2>CRM Pipeline</h2><div className={styles.pipeline}>{pipeline?.stages.map(item => <div key={item.stage}><span>{item.stage.replaceAll('_', ' ')}</span><strong>{item.count}</strong></div>)}</div></article>
      <article className={styles.card}><h2>Team</h2><div className={styles.list}>{team.map(member => <div key={member.user_id}><span><b>{member.name}</b><small>{member.email}</small></span><strong>{member.role}</strong></div>)}</div><form onSubmit={addTeamMember} className={styles.miniForm}><input name="name" placeholder="Name" required /><input name="email" type="email" placeholder="Email" required /><select name="role" defaultValue="acquisitions"><option value="acquisitions">Acquisitions</option><option value="disposition">Disposition</option><option value="transaction_coordinator">Transaction coordinator</option><option value="manager">Manager</option><option value="admin">Admin</option><option value="viewer">Viewer</option></select><button disabled={loading}>Add member</button></form></article>
    </section>
    <section className={styles.grid}>
      <article className={styles.card}><h2>Workspace Leads</h2><div className={styles.list}>{leads.length ? leads.map(lead => <div key={lead.id}><span><b>{lead.seller_name}</b><small>{lead.address}, {lead.city} {lead.state}</small></span><strong>{lead.status}</strong></div>) : <p>No tenant-scoped leads yet. Use Import existing.</p>}</div></article>
      <article className={styles.card}><h2>Follow-ups</h2><div className={styles.list}>{followUps.length ? followUps.map(task => <div key={task.id}><span><b>{task.title}</b><small>Priority {task.priority}{task.due_at ? ` · ${new Date(task.due_at).toLocaleString()}` : ''}</small></span><strong>{task.status}</strong></div>) : <p>No follow-ups queued.</p>}</div></article>
    </section>
  </main>;
}
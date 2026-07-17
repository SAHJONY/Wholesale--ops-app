'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import styles from './owner.module.css';

const API_URL = 'https://backend-pi-opal-65.vercel.app';
const SESSION_STORAGE = 'sahjony_owner_session';

type Principal = { organization_id: number; organization_name: string; user_id: number; email: string; name: string; role: string };
type Pipeline = { total_leads: number; active_deals: number; projected_assignment_revenue: number; stages: Array<{ stage: string; count: number }> };
type Lead = { id: number; seller_name: string; phone: string; status: string; address?: string; city?: string; state?: string; mao?: number };
type FollowUp = { id: number; title: string; status: string; priority: number; due_at?: string; lead_id?: number };
type TeamMember = { user_id: number; name: string; email: string; role: string; active: boolean };
type AuthMode = 'login' | 'request-reset' | 'reset-password';

function money(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);
}

export default function OwnerWorkspace() {
  const [sessionToken, setSessionToken] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [resetCode, setResetCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [authMode, setAuthMode] = useState<AuthMode>('login');
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = useCallback(async (path: string, options: RequestInit = {}, tokenOverride?: string) => {
    const token = (tokenOverride ?? sessionToken).trim();
    let response: Response;
    try {
      response = await fetch(`${API_URL}${path}`, {
        ...options,
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
  }, [sessionToken]);

  const loadWorkspace = useCallback(async (tokenOverride?: string) => {
    const token = (tokenOverride ?? sessionToken).trim();
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const [me, pipelineData, leadData, followUpData, teamData] = await Promise.all([
        request('/auth/me', {}, token),
        request('/crm/pipeline', {}, token),
        request('/crm/leads', {}, token),
        request('/crm/follow-ups', {}, token),
        request('/auth/team', {}, token),
      ]);
      window.localStorage.setItem(SESSION_STORAGE, token);
      setSessionToken(token);
      setPrincipal(me);
      setPipeline(pipelineData);
      setLeads(leadData);
      setFollowUps(followUpData);
      setTeam(teamData);
    } catch (err) {
      window.localStorage.removeItem(SESSION_STORAGE);
      setSessionToken('');
      setPrincipal(null);
      setError(err instanceof Error ? err.message : 'Unable to load workspace');
    } finally {
      setLoading(false);
    }
  }, [request, sessionToken]);

  useEffect(() => {
    const stored = window.localStorage.getItem(SESSION_STORAGE) || '';
    if (stored) void loadWorkspace(stored);
  }, [loadWorkspace]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${API_URL}/human-auth/login`, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Login failed');
      const token = String(data.access_token || '');
      if (!token) throw new Error('Login did not return a session token');
      setPassword('');
      await loadWorkspace(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in');
    } finally {
      setLoading(false);
    }
  }

  async function requestReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${API_URL}/human-auth/request-password-reset`, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to send reset code');
      setNotice(data.message || 'Reset code sent. Check your email.');
      setAuthMode('reset-password');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send reset code');
    } finally {
      setLoading(false);
    }
  }

  async function resetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${API_URL}/human-auth/reset-password`, {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          code: resetCode.trim(),
          password: newPassword,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to reset password');
      setPassword(newPassword);
      setNewPassword('');
      setResetCode('');
      setNotice('Password updated. Sign in with your new password.');
      setAuthMode('login');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to reset password');
    } finally {
      setLoading(false);
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

  function signOut() {
    const token = sessionToken;
    window.localStorage.removeItem(SESSION_STORAGE);
    setSessionToken('');
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
        <h1>{authMode === 'login' ? 'Owner Sign In' : authMode === 'request-reset' ? 'Forgot Password' : 'Reset Password'}</h1>
        <p>{authMode === 'login' ? 'Sign in from any phone or computer.' : authMode === 'request-reset' ? 'We will email you a six-digit reset code.' : 'Enter the code from your email and choose a new password.'}</p>
        <small>API: {API_URL}</small>
        {notice && <div className={styles.notice}>{notice}</div>}
        {error && <div className={styles.error}>{error}</div>}

        {authMode === 'login' && <form onSubmit={signIn} className={styles.form}>
          <label htmlFor="owner-email"><b>Email</b></label>
          <input id="owner-email" value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required placeholder="owner@company.com" />
          <label htmlFor="owner-password"><b>Password</b></label>
          <input id="owner-password" value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required placeholder="Your password" />
          <button disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
          <button type="button" className={styles.secondaryButton} onClick={() => { setError(''); setNotice(''); setAuthMode('request-reset'); }}>Forgot password?</button>
        </form>}

        {authMode === 'request-reset' && <form onSubmit={requestReset} className={styles.form}>
          <label htmlFor="reset-email"><b>Email</b></label>
          <input id="reset-email" value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required placeholder="owner@company.com" />
          <button disabled={loading}>{loading ? 'Sending…' : 'Send reset code'}</button>
          <button type="button" className={styles.secondaryButton} onClick={() => { setError(''); setNotice(''); setAuthMode('login'); }}>Back to sign in</button>
        </form>}

        {authMode === 'reset-password' && <form onSubmit={resetPassword} className={styles.form}>
          <label htmlFor="code-email"><b>Email</b></label>
          <input id="code-email" value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required />
          <label htmlFor="reset-code"><b>Six-digit code</b></label>
          <input id="reset-code" value={resetCode} onChange={(event) => setResetCode(event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required minLength={6} maxLength={6} placeholder="000000" />
          <label htmlFor="new-password"><b>New password</b></label>
          <input id="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} type="password" autoComplete="new-password" required minLength={12} placeholder="At least 12 characters" />
          <button disabled={loading}>{loading ? 'Updating…' : 'Reset password'}</button>
          <button type="button" className={styles.secondaryButton} onClick={() => { setError(''); setNotice(''); setAuthMode('request-reset'); }}>Request another code</button>
        </form>}
      </section>
    </main>;
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>OWNER CONTROL PLANE</span><h1>{principal.organization_name}</h1><p>{principal.name} · {principal.role}</p></div>
      <div className={styles.actions}><button onClick={() => void loadWorkspace()} disabled={loading}>Refresh</button><button onClick={importExisting} disabled={loading}>Import existing</button><button onClick={signOut}>Sign out</button></div>
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

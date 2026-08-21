'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import AuthShell from '../../components/AuthShell';

const DEFAULT_DESTINATION = '/owner';
function safeReturnTo() { if (typeof window === 'undefined') return DEFAULT_DESTINATION; const value = new URLSearchParams(window.location.search).get('returnTo') || DEFAULT_DESTINATION; return value.startsWith('/owner') && !value.startsWith('//') ? value : DEFAULT_DESTINATION; }

export default function UnifiedLoginPage() {
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [status, setStatus] = useState<'checking'|'online'|'offline'>('checking'); const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  const destination = useMemo(() => safeReturnTo(), []);

  useEffect(() => { let cancelled = false; async function initialize() { try { const session = await fetch('/api/owner-access/session', { cache:'no-store', credentials:'same-origin' }); const sessionData = await session.json().catch(() => ({})); if (session.ok && sessionData.authenticated) { window.location.replace(destination); return; } const health = await fetch('/api/owner-access/health', { cache:'no-store' }); if (!health.ok) throw new Error(`HTTP ${health.status}`); if (!cancelled) setStatus('online'); } catch { if (!cancelled) setStatus('offline'); } } void initialize(); return () => { cancelled = true; }; }, [destination]);

  async function signIn(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setLoading(true); setError(''); try { const response = await fetch('/api/owner-access/login', { method:'POST', cache:'no-store', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email:email.trim().toLowerCase(),password}) }); const text = await response.text(); let data:Record<string,unknown>={}; try { data=text?JSON.parse(text):{}; } catch { throw new Error(`Unreadable sign-in response (HTTP ${response.status}).`); } if(!response.ok) throw new Error(`${String(data.detail||'Sign-in failed')} (HTTP ${response.status})`); window.localStorage.removeItem('sahjony_owner_session'); window.location.replace(destination); } catch(err) { setError(err instanceof Error?err.message:'Unable to sign in.'); } finally { setLoading(false); } }

  return <AuthShell eyebrow="EXECUTIVE ACCESS" title="Welcome back." description="Sign in to your private wholesale operations command center." footer={<><span>Protected by a secure same-origin HttpOnly session.</span><Link href="/forgot-password">Recover access</Link></>}>
    <div className={`authStatus authStatus--${status}`} role="status"><i/>{status==='online'?'All systems operational':status==='offline'?'System temporarily unavailable':'Checking secure gateway…'}</div>
    {error?<div className="authAlert" role="alert">{error}</div>:null}
    <form className="authForm" onSubmit={signIn}>
      <label htmlFor="app-email"><span>Business email</span><input id="app-email" value={email} onChange={event=>setEmail(event.target.value)} type="email" autoComplete="username" placeholder="you@company.com" required autoFocus /></label>
      <label htmlFor="app-password"><span>Password</span><input id="app-password" value={password} onChange={event=>setPassword(event.target.value)} type="password" autoComplete="current-password" placeholder="Enter your password" required /></label>
      <div className="authFormMeta"><span>Authorized personnel only</span><Link href="/forgot-password">Forgot password?</Link></div>
      <button className="authSubmit" type="submit" disabled={loading||status!=='online'}>{loading?'Authenticating…':'Enter command center'}<span aria-hidden="true">→</span></button>
    </form>
  </AuthShell>;
}

'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';

const OWNER_EMAIL = 'sahjonycapitalllc@outlook.com';
const DEFAULT_DESTINATION = '/owner';

function safeReturnTo() {
  if (typeof window === 'undefined') return DEFAULT_DESTINATION;
  const value = new URLSearchParams(window.location.search).get('returnTo') || DEFAULT_DESTINATION;
  return value.startsWith('/owner') && !value.startsWith('//') ? value : DEFAULT_DESTINATION;
}

export default function UnifiedLoginPage() {
  const [email, setEmail] = useState(OWNER_EMAIL);
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Checking system…');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const destination = useMemo(() => safeReturnTo(), []);

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      try {
        const session = await fetch('/api/owner-access/session', { cache: 'no-store', credentials: 'same-origin' });
        const sessionData = await session.json().catch(() => ({}));
        if (session.ok && sessionData.authenticated) {
          window.location.replace(destination);
          return;
        }
        const health = await fetch('/api/owner-access/health', { cache: 'no-store' });
        if (!health.ok) throw new Error(`HTTP ${health.status}`);
        if (!cancelled) setStatus('System online');
      } catch {
        if (!cancelled) setStatus('System temporarily unavailable');
      }
    }
    void initialize();
    return () => { cancelled = true; };
  }, [destination]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/owner-access/login', {
        method: 'POST',
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      const text = await response.text();
      let data: Record<string, unknown> = {};
      try { data = text ? JSON.parse(text) : {}; }
      catch { throw new Error(`Unreadable sign-in response (HTTP ${response.status}).`); }
      if (!response.ok) throw new Error(`${String(data.detail || 'Sign-in failed')} (HTTP ${response.status})`);
      window.localStorage.removeItem('sahjony_owner_session');
      window.location.replace(destination);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{minHeight:'100vh',display:'grid',placeItems:'center',background:'radial-gradient(circle at top,#172033 0,#090b10 48%)',color:'#fff',padding:24}}>
      <section style={{width:'100%',maxWidth:480,background:'rgba(21,25,35,.96)',border:'1px solid #2a3140',borderRadius:20,padding:32,boxShadow:'0 24px 80px rgba(0,0,0,.42)'}}>
        <p style={{letterSpacing:2.4,fontSize:12,color:'#9fb0c8',marginBottom:8}}>SAHJONY WHOLESALE OS</p>
        <h1 style={{fontSize:34,margin:'0 0 10px'}}>Sign in</h1>
        <p style={{color:'#b8c2d1',lineHeight:1.55}}>One secure sign-in gives you access to every authorized section of the application.</p>
        <div style={{padding:'10px 12px',borderRadius:10,background:'#10141d',border:'1px solid #273042',margin:'18px 0',color:status==='System online'?'#bff5d0':'#ffd1d1'}}>{status}</div>
        {error && <div style={{background:'#421f26',border:'1px solid #7a3440',padding:12,borderRadius:10,marginBottom:16}}>{error}</div>}
        <form onSubmit={signIn} style={{display:'grid',gap:12}}>
          <label htmlFor="app-email"><b>Email</b></label>
          <input id="app-email" value={email} onChange={e=>setEmail(e.target.value)} type="email" autoComplete="email" required style={{padding:13,borderRadius:9,border:'1px solid #3b465a',fontSize:16}} />
          <label htmlFor="app-password"><b>Password</b></label>
          <input id="app-password" value={password} onChange={e=>setPassword(e.target.value)} type="password" autoComplete="current-password" required style={{padding:13,borderRadius:9,border:'1px solid #3b465a',fontSize:16}} />
          <button type="submit" disabled={loading || status !== 'System online'} style={{padding:13,borderRadius:9,fontWeight:800,fontSize:16,cursor:'pointer'}}>{loading?'Signing in…':'Sign in to SAHJONY Wholesale OS'}</button>
        </form>
        <p style={{marginTop:14}}><Link href="/forgot-password" style={{color:'#b8d4ff'}}>Forgot password?</Link></p>
        <p style={{marginTop:18,color:'#9fb0c8',fontSize:13}}>Authentication uses a secure same-origin HttpOnly session cookie.</p>
      </section>
    </main>
  );
}

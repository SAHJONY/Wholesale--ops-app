'use client';

import { FormEvent, useEffect, useState } from 'react';

const API_URL = 'https://backend-pi-opal-65.vercel.app';
const SESSION_STORAGE = 'sahjony_owner_session';
const OWNER_EMAIL = 'sahjonycapitalllc@outlook.com';

export default function OwnerAccessPage() {
  const [email, setEmail] = useState(OWNER_EMAIL);
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Checking backend...');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/owner-access/health', { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Backend returned HTTP ${response.status}`);
        }
        setStatus('Backend online');
      })
      .catch(err => setStatus(`Backend check failed: ${err instanceof Error ? err.message : 'Unknown error'}`));
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/owner-access/login', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });
      const text = await response.text();
      let data: any = {};
      try { data = text ? JSON.parse(text) : {}; } catch { throw new Error(`Unreadable backend response (HTTP ${response.status})`); }
      if (!response.ok) throw new Error(`${data.detail || 'Login failed'} (HTTP ${response.status})`);
      const token = String(data.access_token || '');
      if (!token) throw new Error('Login succeeded without a session token.');
      window.localStorage.setItem(SESSION_STORAGE, token);
      window.location.replace('/owner/deals');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{minHeight:'100vh',display:'grid',placeItems:'center',background:'#090b10',color:'#fff',padding:24}}>
      <section style={{width:'100%',maxWidth:460,background:'#151923',border:'1px solid #2a3140',borderRadius:16,padding:28}}>
        <p style={{letterSpacing:2,fontSize:12,color:'#9fb0c8'}}>SAHJONY WHOLESALE OS</p>
        <h1>Owner Access Recovery</h1>
        <p>This page uses a secure same-origin proxy to reach the production Vercel backend.</p>
        <p><strong>API:</strong> {API_URL}</p>
        <p>{status}</p>
        {error && <div style={{background:'#421f26',padding:12,borderRadius:8,marginBottom:16}}>{error}</div>}
        <form onSubmit={signIn} style={{display:'grid',gap:12}}>
          <label>Email</label>
          <input value={email} onChange={e=>setEmail(e.target.value)} type="email" required style={{padding:12,borderRadius:8}} />
          <label>Password</label>
          <input value={password} onChange={e=>setPassword(e.target.value)} type="password" required style={{padding:12,borderRadius:8}} />
          <button type="submit" disabled={loading} style={{padding:12,borderRadius:8,fontWeight:700}}>{loading?'Signing in...':'Sign in and open Contracts'}</button>
        </form>
        <p style={{marginTop:16}}><a href="/owner" style={{color:'#a8c7ff'}}>Return to standard owner page</a></p>
      </section>
    </main>
  );
}

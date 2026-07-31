'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';

const OWNER_EMAIL = 'sahjonycapitalllc@outlook.com';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState(OWNER_EMAIL);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [step, setStep] = useState<'request' | 'reset'>('request');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function post(action: string, payload: Record<string, string>) {
    const response = await fetch(`/api/owner-access/${action}`, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const text = await response.text();
    let data: Record<string, unknown> = {};
    try { data = text ? JSON.parse(text) : {}; } catch { throw new Error(`Unreadable response (HTTP ${response.status})`); }
    if (!response.ok) throw new Error(String(data.detail || `Request failed (HTTP ${response.status})`));
    return data;
  }

  async function requestReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError(''); setMessage('');
    try {
      const data = await post('request-password-reset', { email: email.trim().toLowerCase() });
      setMessage(String(data.message || 'A reset code was sent if the account exists.'));
      setStep('reset');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to request reset.'); }
    finally { setLoading(false); }
  }

  async function resetPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError(''); setMessage('');
    if (password !== confirmPassword) { setError('Passwords do not match.'); setLoading(false); return; }
    try {
      const data = await post('reset-password', { email: email.trim().toLowerCase(), code, password });
      setMessage(String(data.message || 'Password updated.'));
      setTimeout(() => { window.location.href = '/login'; }, 1200);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to reset password.'); }
    finally { setLoading(false); }
  }

  return (
    <main style={{minHeight:'100vh',display:'grid',placeItems:'center',background:'radial-gradient(circle at top,#172033 0,#090b10 48%)',color:'#fff',padding:24}}>
      <section style={{width:'100%',maxWidth:500,background:'rgba(21,25,35,.96)',border:'1px solid #2a3140',borderRadius:20,padding:32}}>
        <p style={{letterSpacing:2.4,fontSize:12,color:'#9fb0c8'}}>SAHJONY WHOLESALE OS</p>
        <h1>{step === 'request' ? 'Reset owner password' : 'Enter reset code'}</h1>
        <p style={{color:'#b8c2d1'}}>Password recovery uses the secure same-origin authentication gateway.</p>
        {error && <div style={{background:'#421f26',padding:12,borderRadius:10,margin:'16px 0'}}>{error}</div>}
        {message && <div style={{background:'#173b2a',padding:12,borderRadius:10,margin:'16px 0'}}>{message}</div>}
        {step === 'request' ? (
          <form onSubmit={requestReset} style={{display:'grid',gap:12}}>
            <label htmlFor="reset-email"><b>Email</b></label>
            <input id="reset-email" type="email" value={email} onChange={e=>setEmail(e.target.value)} required style={{padding:13,borderRadius:9,fontSize:16}} />
            <button disabled={loading} style={{padding:13,borderRadius:9,fontWeight:800}}>{loading?'Sending…':'Send reset code'}</button>
          </form>
        ) : (
          <form onSubmit={resetPassword} style={{display:'grid',gap:12}}>
            <label htmlFor="reset-code"><b>6-digit code</b></label>
            <input id="reset-code" inputMode="numeric" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))} required style={{padding:13,borderRadius:9,fontSize:16}} />
            <label htmlFor="new-password"><b>New password</b></label>
            <input id="new-password" type="password" minLength={12} value={password} onChange={e=>setPassword(e.target.value)} required style={{padding:13,borderRadius:9,fontSize:16}} />
            <label htmlFor="confirm-password"><b>Confirm password</b></label>
            <input id="confirm-password" type="password" minLength={12} value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} required style={{padding:13,borderRadius:9,fontSize:16}} />
            <button disabled={loading} style={{padding:13,borderRadius:9,fontWeight:800}}>{loading?'Updating…':'Update password'}</button>
          </form>
        )}
        <p style={{marginTop:18}}><Link href="/login" style={{color:'#b8d4ff'}}>Return to sign in</Link></p>
      </section>
    </main>
  );
}

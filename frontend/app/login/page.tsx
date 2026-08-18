'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';

const DEFAULT_DESTINATION = '/owner';

function safeReturnTo() {
  if (typeof window === 'undefined') return DEFAULT_DESTINATION;
  const value = new URLSearchParams(window.location.search).get('returnTo') || DEFAULT_DESTINATION;
  return value.startsWith('/owner') && !value.startsWith('//') ? value : DEFAULT_DESTINATION;
}

export default function UnifiedLoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Checking system…');
  const [systemOnline, setSystemOnline] = useState<boolean | null>(null);
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
        if (!cancelled) {
          setSystemOnline(true);
          setStatus('System online');
        }
      } catch {
        if (!cancelled) {
          setSystemOnline(false);
          setStatus('System status unavailable — sign-in remains available');
        }
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

  const statusClass = systemOnline === true ? 'online' : systemOnline === false ? 'offline' : '';

  return <main className="premiumLogin">
    <section className="premiumLoginVisual" aria-label="SAHJONY Wholesale Operating System">
      <div className="premiumLoginBrand">
        <span className="premiumLoginBrandMark">S</span>
        <span>SAHJONY WHOLESALE OS</span>
      </div>
      <div className="premiumLoginHero">
        <small>Private acquisition infrastructure</small>
        <h1>Source. Verify.<span>Acquire.</span></h1>
        <p>A precision operating environment for distressed-property intelligence, underwriting, seller execution, disposition and closing.</p>
      </div>
      <div className="premiumLoginMeta">
        <span>Supervised autonomy</span>
        <span>Owner access</span>
        <span>Houston · Nationwide</span>
      </div>
    </section>

    <section className="premiumLoginPanel">
      <div className="premiumLoginCard">
        <span className="kicker">Secure workspace access</span>
        <h2>Welcome back.</h2>
        <p>Enter the owner operating system. One authenticated session unlocks every authorized workflow.</p>

        <div className={`premiumStatus ${statusClass}`}>
          <span className="premiumStatusDot" aria-hidden="true" />
          <span>{status}</span>
        </div>

        {error && <div className="premiumLoginError" role="alert">{error}</div>}

        <form onSubmit={signIn} className="premiumLoginForm">
          <label htmlFor="app-email">Email</label>
          <input id="app-email" value={email} onChange={e => setEmail(e.target.value)} type="email" autoComplete="email" required />
          <label htmlFor="app-password">Password</label>
          <input id="app-password" value={password} onChange={e => setPassword(e.target.value)} type="password" autoComplete="current-password" required />
          <button type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Enter Wholesale OS'}</button>
        </form>

        <div className="premiumLoginLinks">
          <Link href="/forgot-password">Forgot password?</Link>
          <span>HttpOnly secure session</span>
        </div>
      </div>
    </section>
  </main>;
}

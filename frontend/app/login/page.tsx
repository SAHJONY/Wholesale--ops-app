'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import AuthShell from '../../components/AuthShell';

const DEFAULT_DESTINATION = '/owner';
function safeReturnTo() { if (typeof window === 'undefined') return DEFAULT_DESTINATION; const value = new URLSearchParams(window.location.search).get('returnTo') || DEFAULT_DESTINATION; return value.startsWith('/owner') && !value.startsWith('//') ? value : DEFAULT_DESTINATION; }

function formatCountdown(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

export default function UnifiedLoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Checking system…');
  const [systemOnline, setSystemOnline] = useState<boolean | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [retryAfter, setRetryAfter] = useState(0);
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

  useEffect(() => {
    if (retryAfter <= 0) return;
    const timer = window.setInterval(() => {
      setRetryAfter(value => Math.max(0, value - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [retryAfter > 0]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (retryAfter > 0) return;
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

      if (response.status === 429) {
        const seconds = Math.max(1, Number.parseInt(response.headers.get('retry-after') || '0', 10) || 0);
        setRetryAfter(seconds);
        setError(String(data.detail || 'Account temporarily locked.'));
        return;
      }

      if (!response.ok) throw new Error(`${String(data.detail || 'Sign-in failed')} (HTTP ${response.status})`);
      window.localStorage.removeItem('sahjony_owner_session');
      window.location.replace(destination);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.');
    } finally {
      setLoading(false);
    }
  }

  const locked = retryAfter > 0;

  const statusTone = systemOnline === true ? 'online' : systemOnline === false ? 'offline' : 'checking';
  return <AuthShell eyebrow="EXECUTIVE ACCESS" title="Welcome back." description="Sign in to your private wholesale operations command center." footer={<><span>Protected by a secure same-origin HttpOnly session.</span><Link href="/forgot-password">Recover access</Link></>}>
    <div className={`authStatus authStatus--${statusTone}`} role="status"><i />{status}</div>
    {error ? <div className="authAlert" role="alert"><div>{error}</div>{locked ? <div>Try again in <strong>{formatCountdown(retryAfter)}</strong> or <Link href="/forgot-password"> reset your password</Link>.</div> : null}</div> : null}
    <form className="authForm" onSubmit={signIn}>
      <label htmlFor="app-email"><span>Executive account email</span><input id="app-email" value={email} onChange={event => setEmail(event.target.value)} type="email" autoComplete="username" placeholder="Authorized owner email" required disabled={locked} autoFocus /></label>
      <label htmlFor="app-password"><span>Password</span><input id="app-password" value={password} onChange={event => setPassword(event.target.value)} type="password" autoComplete="current-password" placeholder="Enter your password" required disabled={locked} /></label>
      <div className="authFormMeta"><span>Authorized personnel only</span><Link href="/forgot-password">Forgot password?</Link></div>
      <button className="authSubmit" type="submit" disabled={loading || locked}>{locked ? `Locked ${formatCountdown(retryAfter)}` : loading ? 'Authenticating…' : 'Enter command center'}<span aria-hidden="true">→</span></button>
    </form>
  </AuthShell>;
}

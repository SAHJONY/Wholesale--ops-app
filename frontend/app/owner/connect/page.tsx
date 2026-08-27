'use client';

import { useState } from 'react';

type Mode = 'text' | 'voice' | 'video';

type ConnectSession = {
  launch_url?: string;
  owner_url?: string;
  detail?: string;
  billing_mode?: string;
  billing_exempt?: boolean;
};

export default function WholesaleConnectPage() {
  const [contextId, setContextId] = useState('owner-command-center');
  const [contactName, setContactName] = useState('');
  const [loading, setLoading] = useState<Mode | null>(null);
  const [message, setMessage] = useState('');

  async function start(mode: Mode) {
    setLoading(mode);
    setMessage('');
    try {
      const response = await fetch('/api/connect/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ mode, contextId, contactName }),
      });
      const data = (await response.json().catch(() => ({}))) as ConnectSession;
      if (!response.ok || !data.launch_url) throw new Error(data.detail || 'Unable to start SAHJONY Connect session');
      window.location.assign(data.owner_url || data.launch_url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to start SAHJONY Connect session');
      setLoading(null);
    }
  }

  return <main style={{ padding: '32px', maxWidth: 1180, margin: '0 auto' }}>
    <section style={{ border: '1px solid rgba(255,255,255,.1)', borderRadius: 24, padding: 28, background: 'linear-gradient(145deg,#07111b,#02070c)' }}>
      <span style={{ color: '#64e5ff', fontSize: 11, fontWeight: 900, letterSpacing: '.18em' }}>SAHJONY CONNECT · INTERNAL FREE</span>
      <h1 style={{ margin: '12px 0', fontSize: 'clamp(38px,5vw,68px)', lineHeight: .95 }}>Communicate from the deal context.</h1>
      <p style={{ color: '#9db2c1', maxWidth: 760, lineHeight: 1.7 }}>Open secure chat, voice or video for a seller, buyer or active wholesale deal without moving the underlying deal data into CONNECT. Only an opaque context reference is shared.</p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 12, marginTop: 26 }}>
        <label style={{ display: 'grid', gap: 7, color: '#9db2c1', fontSize: 12 }}>
          DEAL / LEAD CONTEXT ID
          <input value={contextId} onChange={event => setContextId(event.target.value)} placeholder="deal-123 or lead-456" style={{ border: '1px solid rgba(255,255,255,.12)', background: '#07131e', color: 'white', borderRadius: 12, padding: 13 }} />
        </label>
        <label style={{ display: 'grid', gap: 7, color: '#9db2c1', fontSize: 12 }}>
          CONTACT NAME · OPTIONAL
          <input value={contactName} onChange={event => setContactName(event.target.value)} placeholder="Seller or buyer name" style={{ border: '1px solid rgba(255,255,255,.12)', background: '#07131e', color: 'white', borderRadius: 12, padding: 13 }} />
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 12, marginTop: 20 }}>
        {(['text','voice','video'] as Mode[]).map(mode => <button key={mode} disabled={Boolean(loading)} onClick={() => start(mode)} style={{ padding: 17, borderRadius: 14, border: '1px solid rgba(255,255,255,.13)', background: '#0b1e2c', color: 'white', fontWeight: 900, cursor: 'pointer' }}>{loading === mode ? 'Starting…' : mode === 'text' ? 'Secure Chat' : mode === 'voice' ? 'Voice Room' : 'Video Room'}</button>)}
      </div>

      <aside style={{ marginTop: 20, padding: 16, borderRadius: 14, background: 'rgba(255,255,255,.04)', color: '#9db2c1', lineHeight: 1.6, fontSize: 12 }}>
        Internal SAHJONY projects are billing-exempt inside CONNECT. External provider costs such as AI model usage, PSTN/SMS, or paid TURN infrastructure are separate. AI assistance is OFF by default in this pilot; no contract, price, payment or closing authority is delegated to CONNECT.
      </aside>
      {message ? <p style={{ color: '#ff9aa7', marginTop: 14 }}>{message}</p> : null}
    </section>
  </main>;
}

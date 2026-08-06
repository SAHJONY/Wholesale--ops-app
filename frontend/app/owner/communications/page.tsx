'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = '/api/backend';
const SESSION_STORAGE = 'sahjony_owner_session';

type Lead = {
  id: number;
  seller_name: string;
  phone: string;
  email?: string;
  status: string;
  property?: { address: string; city: string; state: string; zip_code: string };
};

type Decision = {
  decision_id: number;
  lead_id: number;
  channel: string;
  contact: string;
  allowed: boolean;
  reasons: string[];
  expires_at?: string;
};

type Outbound = {
  id: number;
  lead_id: number;
  channel: string;
  provider: string;
  contact: string;
  status: string;
  provider_reference?: string;
  provider_status?: string;
  error?: string;
  created_at: string;
  dispatched_at?: string;
  // Set while the request is waiting on owner review. Its presence is what
  // puts the row in the approval queue, and its value is what a decision is
  // posted against.
  pending_approval_id?: number | null;
};

type PendingApproval = {
  id: number;
  entity_type: string;
  entity_id: number;
  action_type: string;
  summary: string;
};

export default function CommunicationCenter() {
  const [token, setToken] = useState('');
  const [leads, setLeads] = useState<Lead[]>([]);
  const [outbound, setOutbound] = useState<Outbound[]>([]);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [channel, setChannel] = useState<'sms' | 'automated_call'>('sms');
  const [decision, setDecision] = useState<Decision | null>(null);
  const [latestRequest, setLatestRequest] = useState<{ request_id: number; approval_id: number } | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const selectedLead = useMemo(
    () => leads.find(item => item.id === selectedLeadId) || leads[0],
    [leads, selectedLeadId],
  );

  const request = useCallback(async (path: string, options: RequestInit = {}, tokenOverride?: string) => {
    const activeToken = tokenOverride || token;
    if (!activeToken) throw new Error('Sign in on the owner dashboard first.');
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${activeToken}`,
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {

      setToken('');
      throw new Error('Owner session expired. Sign in again.');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, [token]);

  const load = useCallback(async (tokenOverride?: string) => {
    setLoading(true); setError('');
    try {
      // Two calls, not three. The lead list came from the activation snapshot
      // and the approval queue from the executive command centre; both of those
      // dashboards are gone, and both were indirections over data these two
      // endpoints already hold.
      const [leadList, requests] = await Promise.all([
        request('/crm/leads', {}, tokenOverride),
        request('/outbound/requests', {}, tokenOverride),
      ]);
      const outboundRequests = requests || [];
      setLeads(leadList || []);
      setOutbound(outboundRequests);
      setApprovals(
        outboundRequests
          .filter((item: Outbound) => item.pending_approval_id)
          .map((item: Outbound) => ({
            id: item.pending_approval_id as number,
            action_type: `dispatch_${item.channel}`,
            entity_type: 'outbound_request',
            entity_id: item.id,
            summary: `${item.channel} to ${item.contact}`,
          })),
      );
      if (!selectedLeadId && leadList?.length) setSelectedLeadId(leadList[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load communications');
    } finally { setLoading(false); }
  }, [request, selectedLeadId]);

  useEffect(() => {
    const stored = 'cookie-session';
    setToken(stored);
    if (stored) void load(stored);
  }, [load]);

  function resetAuthorization() {
    setDecision(null);
    setLatestRequest(null);
    setNotice('');
    setError('');
  }

  async function recordDnc(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedLead) return;
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      await request('/compliance/dnc-checks', {
        method: 'POST',
        body: JSON.stringify({
          lead_id: selectedLead.id,
          phone: form.get('phone'),
          provider: form.get('provider'),
          national_dnc: form.get('national_dnc') === 'on',
          state_dnc: form.get('state_dnc') === 'on',
          raw_reference: { recorded_from: 'owner_communication_center' },
        }),
      });
      setNotice('Fresh DNC result recorded.');
      setDecision(null);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to record DNC result'); }
    finally { setLoading(false); }
  }

  async function recordConsent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedLead) return;
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      await request('/compliance/consents', {
        method: 'POST',
        body: JSON.stringify({
          lead_id: selectedLead.id,
          channel,
          contact: selectedLead.phone,
          consent_type: 'prior_express_written_consent',
          source: form.get('source'),
          evidence: { note: form.get('evidence'), recorded_from: 'owner_communication_center' },
        }),
      });
      setNotice(`Consent evidence recorded for ${channel.replace('_', ' ')}.`);
      setDecision(null);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to record consent'); }
    finally { setLoading(false); }
  }

  async function evaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedLead) return;
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice(''); setLatestRequest(null);
    try {
      const result = await request('/compliance/evaluate', {
        method: 'POST',
        body: JSON.stringify({
          lead_id: selectedLead.id,
          channel,
          contact: selectedLead.phone,
          recipient_timezone: form.get('recipient_timezone') || undefined,
        }),
      });
      setDecision(result);
      setNotice(result.allowed ? 'Compliance authorization issued for 15 minutes.' : `Communication blocked: ${(result.reasons || []).join(', ')}`);
    } catch (err) { setError(err instanceof Error ? err.message : 'Compliance evaluation failed'); }
    finally { setLoading(false); }
  }

  async function createRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedLead || !decision?.allowed) return;
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      const content = channel === 'sms'
        ? { body: form.get('body') }
        : {
            task: form.get('task'),
            first_sentence: form.get('first_sentence'),
            language: form.get('language') || 'en',
            timezone: form.get('timezone'),
            max_duration: 10,
          };
      const result = await request('/outbound/requests', {
        method: 'POST',
        body: JSON.stringify({
          lead_id: selectedLead.id,
          channel,
          provider: channel === 'sms' ? 'twilio' : 'bland',
          contact: selectedLead.phone,
          compliance_decision_id: decision.decision_id,
          content,
        }),
      });
      setLatestRequest({ request_id: result.request_id, approval_id: result.approval_id });
      setNotice(`Outbound request #${result.request_id} created. Owner approval is required.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to create outbound request'); }
    finally { setLoading(false); }
  }

  async function decideApproval(approvalId: number, decisionValue: 'approved' | 'rejected') {
    setLoading(true); setError(''); setNotice('');
    try {
      await request(`/workspace/approvals/${approvalId}/decision`, {
        method: 'POST', body: JSON.stringify({ decision: decisionValue }),
      });
      setNotice(`Outbound request ${decisionValue}.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to decide approval'); }
    finally { setLoading(false); }
  }

  async function dispatch(requestId: number) {
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request(`/outbound/requests/${requestId}/dispatch`, { method: 'POST', body: '{}' });
      setNotice(`${result.provider} accepted request #${requestId}. Provider status: ${result.provider_status || result.status}.`);
      setDecision(null); setLatestRequest(null);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : 'Dispatch failed'); }
    finally { setLoading(false); }
  }

  if (!token) return <main className={styles.setup}><section className={styles.setupCard}>
    <h1>Owner session required</h1><p>Sign in on the owner dashboard, then reopen the Communication Center.</p>
    <a className={styles.linkButton} href="/owner">Go to owner sign in</a>
  </section></main>;

  const pendingByRequest = new Map(approvals.map(item => [item.entity_id, item]));

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>CONTROLLED COMMUNICATIONS</span><h1>Communication Center</h1><p>Record compliance evidence, request owner approval, and dispatch through Bland AI or Twilio.</p></div>
      <div className={styles.actions}><button onClick={() => void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner">Control Plane</a></div>
    </header>

    {notice && <div className={styles.notice}>{notice}</div>}{error && <div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Workspace leads</span><strong>{leads.length}</strong></article>
      <article><span>Outbound requests</span><strong>{outbound.length}</strong></article>
      <article><span>Pending approvals</span><strong>{approvals.length}</strong></article>
      <article><span>Authorization</span><strong>{decision?.allowed ? 'ALLOWED' : decision ? 'BLOCKED' : 'NOT RUN'}</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>RECIPIENT</span><h2>Select seller lead</h2></div>
        <select value={selectedLead?.id || ''} onChange={event => { setSelectedLeadId(Number(event.target.value)); resetAuthorization(); }}>
          {leads.map(item => <option key={item.id} value={item.id}>{item.seller_name} · {item.status} · {item.property?.state || '—'}</option>)}
        </select>
      </div>
      {selectedLead ? <div className={styles.calculation}><b>{selectedLead.seller_name}</b> · {selectedLead.phone} · {selectedLead.property?.address}, {selectedLead.property?.city} {selectedLead.property?.state} {selectedLead.property?.zip_code}</div> : <p>No workspace leads found.</p>}
    </section>

    {selectedLead && <section className={styles.grid}>
      <article className={styles.card}>
        <span className={styles.eyebrow}>COMPLIANCE EVIDENCE</span><h2>DNC and consent</h2>
        <form onSubmit={recordDnc} className={styles.activationForm}>
          <input name="phone" defaultValue={selectedLead.phone} placeholder="Phone" required />
          <input name="provider" placeholder="DNC provider or source" required />
          <label><input name="national_dnc" type="checkbox" /> National DNC match</label>
          <label><input name="state_dnc" type="checkbox" /> State DNC match</label>
          <button disabled={loading}>Record fresh DNC result</button>
        </form>
        <form onSubmit={recordConsent} className={styles.activationForm}>
          <select value={channel} onChange={event => { setChannel(event.target.value as 'sms' | 'automated_call'); resetAuthorization(); }}>
            <option value="sms">SMS through Twilio</option><option value="automated_call">Automated call through Bland AI</option>
          </select>
          <input name="source" placeholder="Consent source, e.g. signed web form" required />
          <textarea name="evidence" placeholder="Describe where and when consent was captured" rows={3} required />
          <button disabled={loading}>Record written consent</button>
        </form>
      </article>

      <article className={styles.card}>
        <span className={styles.eyebrow}>AUTHORIZATION</span><h2>Run compliance evaluation</h2>
        <form onSubmit={evaluate} className={styles.activationForm}>
          <input name="recipient_timezone" placeholder="Recipient timezone, e.g. America/New_York" required={channel === 'automated_call'} />
          <button disabled={loading}>Evaluate exact contact and channel</button>
        </form>
        {decision && <div className={styles.calculation}>
          Decision #{decision.decision_id}: <b>{decision.allowed ? 'ALLOWED' : 'BLOCKED'}</b><br />
          {decision.reasons?.length ? `Reasons: ${decision.reasons.join(', ')}` : `Expires: ${decision.expires_at ? new Date(decision.expires_at).toLocaleTimeString() : '—'}`}
        </div>}

        <form onSubmit={createRequest} className={styles.activationForm}>
          {channel === 'sms' ? <textarea name="body" rows={5} placeholder="Approved SMS content" required /> : <>
            <textarea name="task" rows={5} placeholder="Bland call objective and constraints" required />
            <input name="first_sentence" placeholder="First sentence" />
            <input name="timezone" placeholder="Bland timezone" />
            <select name="language" defaultValue="en"><option value="en">English</option><option value="es">Spanish</option></select>
          </>}
          <button disabled={loading || !decision?.allowed}>Create owner-approval request</button>
        </form>

        {latestRequest && <div className={styles.actions}>
          <button onClick={() => void decideApproval(latestRequest.approval_id, 'approved')} disabled={loading}>Approve</button>
          <button onClick={() => void decideApproval(latestRequest.approval_id, 'rejected')} disabled={loading}>Reject</button>
          <button onClick={() => void dispatch(latestRequest.request_id)} disabled={loading}>Dispatch after approval</button>
        </div>}
      </article>
    </section>}

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>OUTBOUND HISTORY</span><h2>Requests and provider status</h2></div><small>{outbound.length} records</small></div>
      <div className={styles.list}>{outbound.length ? outbound.map(item => {
        const pending = pendingByRequest.get(item.id);
        return <div key={item.id}><span><b>#{item.id} · {item.channel.replace('_', ' ')} via {item.provider}</b><small>{item.contact} · {new Date(item.created_at).toLocaleString()}</small><small>{item.error || item.provider_reference || 'Awaiting provider dispatch'}</small></span><span className={styles.score}>{item.status}{item.provider_status ? ` · ${item.provider_status}` : ''}{pending ? ` · approval #${pending.id} pending` : ''}</span></div>;
      }) : <p>No outbound requests recorded.</p>}</div>
    </section>
  </main>;
}

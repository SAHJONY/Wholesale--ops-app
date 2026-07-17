'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = 'https://backend-pi-opal-65.vercel.app';
const SESSION_STORAGE = 'sahjony_owner_session';
const SIGN_IN_URL = '/owner?returnTo=%2Fowner%2Fdeals';

type Deal = { id:number; property_id:number; stage:string; target_contract_price?:number; target_buyer_price?:number; projected_assignment_fee?:number; next_action?:string };
type Packet = { id:number; deal_id:number; packet_type:string; status:string; signer_name?:string; signer_email?:string; template_id?:string; provider?:string; provider_status?:string; provider_reference?:string; docusign_envelope_id?:string; error?:string; created_at:string; sent_at?:string };
type DocumentItem = { id:number; deal_id:number; packet_id?:number; document_type:string; status:string; storage_key?:string; source:string };
type Readiness = { selected_provider:string; provider_configured:boolean; docuseal_configured:boolean; docusign_configured:boolean; document_storage:boolean };
type Snapshot = { deals:Deal[]; packets:Packet[]; documents:DocumentItem[]; readiness:Readiness };

const emptySnapshot: Snapshot = { deals:[], packets:[], documents:[], readiness:{selected_provider:'docuseal',provider_configured:false,docuseal_configured:false,docusign_configured:false,document_storage:false} };
function money(value?:number) { return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value || 0); }

export default function DealExecutionCenter() {
  const [token,setToken] = useState('');
  const [snapshot,setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [dealId,setDealId] = useState<number | null>(null);
  const [approvalMap,setApprovalMap] = useState<Record<number,number>>({});
  const [notice,setNotice] = useState('');
  const [error,setError] = useState('');
  const [loading,setLoading] = useState(true);
  const [authenticated,setAuthenticated] = useState(false);

  const selectedDeal = useMemo(() => snapshot.deals.find(d => d.id === dealId) || snapshot.deals[0], [snapshot.deals,dealId]);

  const redirectToSignIn = useCallback(() => {
    window.localStorage.removeItem(SESSION_STORAGE);
    setToken('');
    setAuthenticated(false);
    window.location.replace(SIGN_IN_URL);
  }, []);

  const request = useCallback(async(path:string, options:RequestInit={}, override?:string) => {
    const active = override || token;
    if (!active) { redirectToSignIn(); throw new Error('Owner session required.'); }
    const response = await fetch(`${API_URL}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const data = await response.json().catch(()=>({}));
    if (response.status === 401 || response.status === 403) { redirectToSignIn(); throw new Error('Owner session expired.'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  },[token,redirectToSignIn]);

  const load = useCallback(async(override?:string) => {
    setLoading(true); setError('');
    try {
      const data = await request('/deal-execution/snapshot',{},override);
      setSnapshot(data);
      setAuthenticated(true);
      if (!dealId && data.deals?.length) setDealId(data.deals[0].id);
    } catch(err) {
      if (window.location.pathname === '/owner/deals') setError(err instanceof Error ? err.message : 'Unable to load deal execution');
    } finally { setLoading(false); }
  },[request,dealId]);

  useEffect(()=>{
    const stored=window.localStorage.getItem(SESSION_STORAGE)||'';
    if (!stored) { redirectToSignIn(); return; }
    setToken(stored);
    void load(stored);
  },[load,redirectToSignIn]);

  async function prepare(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); if(!selectedDeal) return;
    const form = new FormData(event.currentTarget);
    setLoading(true); setError(''); setNotice('');
    try {
      const result = await request(`/deal-execution/deals/${selectedDeal.id}/packets`,{method:'POST',body:JSON.stringify({
        packet_type:form.get('packet_type'), signature_provider:form.get('signature_provider'), signer_name:form.get('signer_name'), signer_email:form.get('signer_email'),
        contract_price:Number(form.get('contract_price')||0), assignment_fee:Number(form.get('assignment_fee')||0),
        earnest_money:Number(form.get('earnest_money')||100), closing_days:Number(form.get('closing_days')||30),
        buyer_name:form.get('buyer_name')||'Juan Gonzalez', assignment_allowed:true, buyer_pays_closing:true,
      })});
      setApprovalMap(m=>({...m,[result.packet_id]:result.approval_id}));
      setNotice(`Packet #${result.packet_id} prepared through ${result.provider}. Review and approve before sending.`);
      await load();
    } catch(err) { setError(err instanceof Error ? err.message : 'Unable to prepare packet'); }
    finally { setLoading(false); }
  }

  async function decide(packetId:number, decision:'approved'|'rejected') {
    const approvalId = approvalMap[packetId];
    if(!approvalId) { setError('Approval ID is not cached for this packet. Approve it from the main Control Plane.'); return; }
    setLoading(true); setError('');
    try { await request(`/workspace/approvals/${approvalId}/decision`,{method:'POST',body:JSON.stringify({decision})}); setNotice(`Packet ${decision}.`); await load(); }
    catch(err) { setError(err instanceof Error ? err.message : 'Unable to record decision'); }
    finally { setLoading(false); }
  }

  async function send(packetId:number) {
    setLoading(true); setError('');
    try { const result=await request(`/deal-execution/packets/${packetId}/send`,{method:'POST',body:'{}'}); setNotice(`${result.provider || 'E-signature'} request sent: ${result.provider_reference || 'queued'}.`); await load(); }
    catch(err) { setError(err instanceof Error ? err.message : 'Unable to send packet'); }
    finally { setLoading(false); }
  }

  async function initializeClosing(id:number) {
    setLoading(true); setError('');
    try { const result=await request(`/deal-execution/deals/${id}/initialize-closing`,{method:'POST',body:'{}'}); setNotice(`Closing initialized with ${result.items.length} checklist items.`); await load(); }
    catch(err) { setError(err instanceof Error ? err.message : 'Unable to initialize closing'); }
    finally { setLoading(false); }
  }

  if (!authenticated) return <main className={styles.setup}><section className={styles.setupCard}><span className={styles.eyebrow}>DEAL EXECUTION</span><h1>{loading ? 'Checking owner session…' : 'Owner session required'}</h1><p>{error || 'Redirecting to secure owner sign-in.'}</p><a className={styles.linkButton} href={SIGN_IN_URL}>Sign in</a></section></main>;

  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>DEAL EXECUTION</span><h1>Contracts & Closing Center</h1><p>Prepare approved templates, control signatures, and move deals into closing.</p></div><div className={styles.actions}><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/closing">Closing Command</a><a className={styles.linkButton} href="/owner">Control Plane</a><a className={styles.linkButton} href="/owner/communications">Communications</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Deals</span><strong>{snapshot.deals.length}</strong></article>
      <article><span>Contract packets</span><strong>{snapshot.packets.length}</strong></article>
      <article><span>Selected provider</span><strong>{snapshot.readiness.selected_provider || 'docuseal'}</strong></article>
      <article><span>E-signature</span><strong>{snapshot.readiness.provider_configured?'Ready':'Missing'}</strong></article>
      <article><span>Secure storage</span><strong>{snapshot.readiness.document_storage?'Ready':'Missing'}</strong></article>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}>
        <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PREPARE</span><h2>Contract packet</h2></div><select value={selectedDeal?.id||''} onChange={e=>setDealId(Number(e.target.value))}>{snapshot.deals.map(d=><option key={d.id} value={d.id}>Deal #{d.id} · {d.stage}</option>)}</select></div>
        {selectedDeal?<form onSubmit={prepare} className={styles.activationForm}>
          <select name="packet_type" defaultValue="purchase_agreement"><option value="purchase_agreement">Purchase agreement</option><option value="assignment_agreement">Assignment agreement</option></select>
          <select name="signature_provider" defaultValue={snapshot.readiness.selected_provider||'docuseal'}><option value="docuseal">DocuSeal</option><option value="docusign">DocuSign fallback</option></select>
          <input name="signer_name" placeholder="Signer legal name" required />
          <input name="signer_email" type="email" placeholder="Signer email" required />
          <label>Contract price<input name="contract_price" type="number" defaultValue={selectedDeal.target_contract_price||''} required /></label>
          <label>Assignment fee<input name="assignment_fee" type="number" defaultValue={selectedDeal.projected_assignment_fee||''} /></label>
          <label>Earnest money<input name="earnest_money" type="number" defaultValue="100" /></label>
          <label>Closing days<input name="closing_days" type="number" defaultValue="30" /></label>
          <input name="buyer_name" defaultValue="Juan Gonzalez" placeholder="Buyer name" />
          <button disabled={loading}>Prepare and request approval</button>
          <small>Only attorney-approved state templates configured for the selected provider can be used.</small>
        </form>:<p>No active deals. Return to the Control Plane, import existing records, or qualify a lead with ARV and repairs to create a deal.</p>}
      </article>

      <article className={styles.card}><span className={styles.eyebrow}>DEALS</span><h2>Execution queue</h2><div className={styles.list}>{snapshot.deals.length?snapshot.deals.map(d=><div key={d.id}><span><b>Deal #{d.id} · {d.stage}</b><small>Contract {money(d.target_contract_price)} · Buyer {money(d.target_buyer_price)} · Fee {money(d.projected_assignment_fee)}</small><small>{d.next_action||'No next action'}</small></span><button onClick={()=>void initializeClosing(d.id)} disabled={loading}>Initialize closing</button></div>):<p>No workspace deals found. This is now a real zero count, not an authentication fallback.</p>}</div></article>
    </section>

    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>PACKETS</span><h2>Signature workflow</h2></div><strong>{snapshot.packets.length}</strong></div><div className={styles.list}>{snapshot.packets.length?snapshot.packets.map(p=><div key={p.id}><span><b>Packet #{p.id} · {p.packet_type.replaceAll('_',' ')}</b><small>Deal #{p.deal_id} · {p.signer_name||'No signer'} · {p.status} · {p.provider||snapshot.readiness.selected_provider}</small><small>{p.provider_reference?`Reference ${p.provider_reference}`:p.error||'Not sent'}</small></span><span className={styles.decisionButtons}>{p.status==='pending_approval'&&approvalMap[p.id]&&<><button onClick={()=>void decide(p.id,'approved')} disabled={loading}>Approve</button><button onClick={()=>void decide(p.id,'rejected')} disabled={loading}>Reject</button></>}<button onClick={()=>void send(p.id)} disabled={loading||p.status==='sent'||p.status==='completed'}>Send</button></span></div>):<p>No contract packets prepared.</p>}</div></section>

    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>DOCUMENTS</span><h2>Deal document register</h2></div><strong>{snapshot.documents.length}</strong></div><div className={styles.list}>{snapshot.documents.length?snapshot.documents.map(d=><div key={d.id}><span><b>{d.document_type.replaceAll('_',' ')}</b><small>Deal #{d.deal_id} · {d.source}</small></span><strong>{d.status}</strong></div>):<p>No deal documents registered yet.</p>}</div></section>
  </main>;
}

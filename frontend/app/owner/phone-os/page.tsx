'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

type Status = {
  provider:string; inbound_number:string; outbound_number:string; human_transfer_target:string;
  openai_configured:boolean; bland_configured:boolean; qualification_model:string; operating_mode:string;
};
type Call = {
  id:number; lead_id?:number; direction:string; contact:string; status:string; outcome?:string;
  ai_disclosed:boolean; verbal_opt_out:boolean; qualification?:Record<string,unknown>; created_at:string;
};

export default function PhoneOsPage(){
  const [status,setStatus]=useState<Status|null>(null); const [calls,setCalls]=useState<Call[]>([]);
  const [loading,setLoading]=useState(true); const [notice,setNotice]=useState(''); const [error,setError]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={})=>{
    const r=await fetch(`/api/backend${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:'Bearer cookie-session',...(options.headers||{})}});
    const data=await r.json().catch(()=>({}));
    if(r.status===401||r.status===403){location.replace('/owner-access');throw new Error('Owner session required');}
    if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${r.status})`); return data;
  },[]);
  const load=useCallback(async()=>{setLoading(true);setError('');try{const [s,c]=await Promise.all([request('/phone-os/status'),request('/phone-os/calls')]);setStatus(s);setCalls(c||[]);}catch(e){setError(e instanceof Error?e.message:'Unable to load Phone OS');}finally{setLoading(false);}},[request]);
  useEffect(()=>{void load();},[load]);
  async function qualify(id:number){setLoading(true);setError('');setNotice('');try{const r=await request(`/phone-os/calls/${id}/qualify`,{method:'POST',body:'{}'});setNotice(`Call #${id}: ${r.score?.pillars_captured||0}/4 pillars · ${r.score?.hot_lead?'HOT — human handoff':'FOLLOW-UP'}.`);await load();}catch(e){setError(e instanceof Error?e.message:'Qualification failed');}finally{setLoading(false);}}
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>SAHJONY PHONE OS</span><h1>AI Acquisition Phone System</h1><p>Inbound and approved outbound calls flow into structured seller qualification, CRM evidence and supervised human handoff.</p></div><div className={styles.actions}><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/communications">Outbound Communications</a><a className={styles.linkButton} href="/owner/deal-factory">Deal Factory</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}>
      <article><span>Provider</span><strong>{status?.provider?.toUpperCase()||'—'}</strong></article>
      <article><span>Inbound AI</span><strong>{status?.inbound_number||'—'}</strong></article>
      <article><span>Outbound</span><strong>{status?.outbound_number||'—'}</strong></article>
      <article><span>Human transfer</span><strong>{status?.human_transfer_target||'—'}</strong></article>
      <article><span>OpenAI</span><strong>{status?.openai_configured?'READY':'SETUP'}</strong></article>
      <article><span>Bland</span><strong>{status?.bland_configured?'READY':'SETUP'}</strong></article>
    </section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>OPERATING FLOW</span><h2>Seller call → qualification → human/deal handoff</h2></div><strong>{status?.operating_mode||'supervised'}</strong></div>
      <div className={styles.list}><div><span><b>Inbound</b><small>Seller calls the AI line; transcript is stored by the voice engine.</small></span></div><div><span><b>Qualification</b><small>OpenAI extracts only explicit Motivation, Timeline, Condition and Price claims. Missing facts stay null.</small></span></div><div><span><b>Hot lead</b><small>Qualified or complex sellers are escalated to the human transfer target and queued for source-backed underwriting.</small></span></div><div><span><b>Outbound</b><small>Communication Center still requires compliance decision + owner approval before Bland dispatch.</small></span></div></div>
    </section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>CALL INTELLIGENCE</span><h2>Recent voice calls</h2></div><strong>{calls.length}</strong></div>
      <div className={styles.list}>{calls.length?calls.map(call=><div key={call.id}><span><b>Call #{call.id} · {call.direction} · {call.contact}</b><small>{call.status} · {call.outcome||'no outcome'} · AI disclosed {call.ai_disclosed?'yes':'no'} · opt-out {call.verbal_opt_out?'YES':'no'}</small><small>{call.qualification?`Qualified · ${String(call.qualification.summary||'structured evidence saved')}`:'Not yet qualified'}</small></span><span className={styles.decisionButtons}>{!call.qualification&&<button disabled={loading} onClick={()=>void qualify(call.id)}>Qualify transcript</button>}{call.lead_id&&<a className={styles.linkButton} href={`/owner/deal-intelligence?lead=${call.lead_id}`}>Underwrite</a>}</span></div>):<p>No voice calls recorded yet.</p>}</div>
    </section>
  </main>;
}

'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const SESSION = 'sahjony_owner_session';
const SIGN_IN = '/login?returnTo=/owner/properties';

type PropertySummary = { property_id:number; seller_name?:string; status:string; address:string; city:string; state:string; zip_code:string; arv?:number; repairs?:number; mao?:number; deal_id?:number; deal_stage?:string; projected_assignment_fee?:number };
type Workspace = { property:Record<string,any>; seller:Record<string,any>; deal?:Record<string,any>|null; timeline:any[]; follow_ups:any[]; offers:any[]; closing:any[]; approvals:any[]; buyer_matches:any[]; governance:Record<string,boolean> };

function money(value?: number) { return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value||0); }

export default function PropertyWorkspaces() {
  const [items,setItems]=useState<PropertySummary[]>([]); const [selected,setSelected]=useState<Workspace|null>(null); const [error,setError]=useState(''); const [loading,setLoading]=useState(true);
  const request=useCallback(async(path:string)=>{ const token=localStorage.getItem(SESSION)||''; if(!token){location.replace(SIGN_IN);throw new Error('Owner session required');} const response=await fetch(`/api/backend${path}`,{cache:'no-store',headers:{Authorization:`Bearer ${token}`}}); const body=await response.json().catch(()=>({})); if(response.status===401||response.status===403){localStorage.removeItem(SESSION);location.replace(SIGN_IN);throw new Error('Owner session expired');} if(!response.ok) throw new Error(body.detail||`Request failed (${response.status})`); return body;},[]);
  const loadList=useCallback(async()=>{setLoading(true);setError('');try{const data=await request('/property-workspace');setItems(Array.isArray(data)?data:[]);if(data?.length){setSelected(await request(`/property-workspace/${data[0].property_id}`));}}catch(e){setError(e instanceof Error?e.message:'Unable to load properties');}finally{setLoading(false);}},[request]);
  useEffect(()=>{void loadList();},[loadList]);
  async function open(id:number){setError('');try{setSelected(await request(`/property-workspace/${id}`));}catch(e){setError(e instanceof Error?e.message:'Unable to load property');}}
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>CANONICAL OPERATING RECORD</span><h1>Unified Property Workspace</h1><p>Ownership, underwriting, seller activity, buyer matches, offers, approvals, and closing milestones in one workspace.</p></div><div className={styles.actions}><button onClick={()=>void loadList()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/nationwide-acquisition">Import leads</a></div></header>
    {error&&<div className={styles.error}>{error}</div>}
    <section className={styles.grid}>
      <article className={styles.card}><span className={styles.eyebrow}>PORTFOLIO</span><h2>{items.length} properties</h2><div className={styles.list}>{items.map(item=><button key={item.property_id} onClick={()=>void open(item.property_id)}><span><b>{item.address}</b><small>{item.city}, {item.state} {item.zip_code} · {item.seller_name||'Seller pending'}</small></span><strong>{item.deal_stage||item.status}</strong></button>)}{!items.length&&!loading&&<p>No properties yet. Import verified leads from Nationwide Acquisition.</p>}</div></article>
      <article className={styles.card}><span className={styles.eyebrow}>UNDERWRITING</span><h2>{selected?.property?.address||'Select a property'}</h2>{selected&&<div className={styles.metrics}><article><span>ARV</span><strong>{money(selected.property.arv)}</strong></article><article><span>Repairs</span><strong>{money(selected.property.repairs)}</strong></article><article><span>MAO</span><strong>{money(selected.property.mao)}</strong></article><article><span>Assignment</span><strong>{money(selected.deal?.projected_assignment_fee)}</strong></article></div>}<p>{selected?.property?.bedrooms||'—'} bd · {selected?.property?.bathrooms||'—'} ba · {selected?.property?.sqft||'—'} sqft</p></article>
    </section>
    {selected&&<>
      <section className={styles.grid}>
        <article className={styles.card}><span className={styles.eyebrow}>SELLER</span><h2>{selected.seller.name||'Unknown seller'}</h2><p>{selected.seller.phone||'Phone pending'}<br/>{selected.seller.email||'Email pending'}</p><div className={styles.metrics}><article><span>Motivation</span><strong>{selected.seller.motivation_score||0}</strong></article><article><span>Distress</span><strong>{selected.seller.distress_score||0}</strong></article><article><span>Equity</span><strong>{selected.seller.equity_score||0}</strong></article></div></article>
        <article className={styles.card}><span className={styles.eyebrow}>DEAL CONTROL</span><h2>{selected.deal?`Deal #${selected.deal.id}`:'No deal created'}</h2><p>{selected.deal?.next_action||'Qualify and convert this lead when underwriting is complete.'}</p><div className={styles.list}><div><span><b>Stage</b><small>{selected.deal?.stage||'lead'}</small></span><strong>{Math.round((selected.deal?.probability_to_close||0)*100)}%</strong></div><div><span><b>Risk score</b><small>Lower is better</small></span><strong>{selected.deal?.risk_score||0}</strong></div></div></article>
      </section>
      <section className={styles.grid}>
        <article className={styles.card}><span className={styles.eyebrow}>BUYER INTELLIGENCE</span><h2>{selected.buyer_matches.length} matches</h2><div className={styles.list}>{selected.buyer_matches.map((b:any)=><div key={b.id}><span><b>{b.company||b.name}</b><small>{b.closing_days} day close · POF {b.proof_of_funds_verified?'verified':'pending'}</small></span><strong>{Math.round(b.reliability_score)}%</strong></div>)}{!selected.buyer_matches.length&&<p>No matching buyer records yet.</p>}</div></article>
        <article className={styles.card}><span className={styles.eyebrow}>APPROVALS & GOVERNANCE</span><h2>{selected.approvals.length} decisions</h2><div className={styles.list}>{selected.approvals.map((a:any)=><div key={a.id}><span><b>{a.action_type}</b><small>{a.summary}</small></span><strong>{a.status}</strong></div>)}{!selected.approvals.length&&<p>No pending approvals.</p>}</div><small>External actions remain blocked without explicit valid approval.</small></article>
      </section>
      <section className={styles.grid}>
        <article className={styles.card}><span className={styles.eyebrow}>TIMELINE</span><h2>Seller and deal history</h2><div className={styles.list}>{selected.timeline.map((t:any)=><div key={t.id}><span><b>{t.type}</b><small>{t.summary}</small></span><strong>{new Date(t.created_at).toLocaleDateString()}</strong></div>)}{!selected.timeline.length&&<p>No activity recorded yet.</p>}</div></article>
        <article className={styles.card}><span className={styles.eyebrow}>CLOSING</span><h2>{selected.closing.length} milestones</h2><div className={styles.list}>{selected.closing.map((c:any)=><div key={c.id}><span><b>{c.type}</b><small>{c.owner||'Unassigned'}</small></span><strong>{c.status}</strong></div>)}{!selected.closing.length&&<p>Closing has not been initialized.</p>}</div></article>
      </section>
    </>}
  </main>;
}

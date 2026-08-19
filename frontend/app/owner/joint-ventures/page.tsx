'use client';

import { useEffect, useMemo, useState } from 'react';
import styles from './joint-ventures.module.css';

type Activity={id:number;type:string;summary:string;metadata?:Record<string,unknown>;created_at?:string};

function text(value:unknown){return typeof value==='string'?value:'—'}

export default function JointVenturesPage(){
  const [items,setItems]=useState<Activity[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');

  useEffect(()=>{
    let cancelled=false;
    void fetch('/api/backend/crm/activities',{cache:'no-store',headers:{Authorization:'Bearer cookie-session'}})
      .then(async response=>{if(response.status===401||response.status===403){window.location.replace('/login?returnTo=/owner/joint-ventures');throw new Error('Owner session required')}if(!response.ok)throw new Error(`Request failed (${response.status})`);return response.json() as Promise<Activity[]>})
      .then(rows=>{if(!cancelled)setItems((Array.isArray(rows)?rows:[]).filter(item=>item.type==='public_partner_intake'&&text(item.metadata?.role)==='wholesaler_jv'))})
      .catch(err=>{if(!cancelled)setError(err instanceof Error?err.message:'Unable to load JV pipeline')})
      .finally(()=>{if(!cancelled)setLoading(false)});
    return()=>{cancelled=true};
  },[]);

  const recent=useMemo(()=>items.slice(0,25),[items]);
  const underContract=useMemo(()=>items.filter(item=>text(item.metadata?.message).includes('Contract status: under_contract')).length,[items]);
  const needsBuyer=useMemo(()=>items.filter(item=>text(item.metadata?.message).includes('Buyer status: need_buyer')).length,[items]);

  return <main className={styles.page}>
    <header className={styles.hero}><div><span>SAHJONY WHOLESALE OS · JOINT VENTURES</span><h1>JV deal intake, review, and disposition control.</h1><p>Track wholesaler-submitted opportunities without mixing them into verified acquisitions prematurely. Every JV stays gated until authority, economics, title path, buyer demand, and written compensation terms are confirmed.</p></div><div className={styles.actions}><a href="/joint-venture" target="_blank" rel="noreferrer">Open public JV page</a><a href="/owner/deal-intelligence">Underwrite deal</a><a href="/owner/disposition">Buyer matching</a></div></header>

    {error&&<div className={styles.error}>{error}</div>}

    <section className={styles.kpis}><article><span>JV submissions</span><strong>{loading?'—':items.length}</strong><small>Public wholesaler intake</small></article><article><span>Under contract</span><strong>{loading?'—':underContract}</strong><small>Reported, not yet independently verified</small></article><article><span>Need buyers</span><strong>{loading?'—':needsBuyer}</strong><small>Disposition opportunities</small></article><article><span>Execution rule</span><strong>Written JV</strong><small>No compensation inferred from intake</small></article></section>

    <section className={styles.workflow}><div><span>JV CONTROL GATES</span><h2>Promote only after the deal survives all five checks.</h2></div><div className={styles.steps}><article><b>01</b><h3>Authority</h3><p>Confirm direct seller control or a valid assignable contract and any restrictions.</p></article><article><b>02</b><h3>Economics</h3><p>Verify ARV, repairs, seller/contract basis, buyer price, and assignment/JV spread.</p></article><article><b>03</b><h3>Title</h3><p>Confirm ownership, liens, foreclosure timing, probate, and closing structure.</p></article><article><b>04</b><h3>Buyer demand</h3><p>Match verified buyers by ZIP, price, rehab, close speed, and POF status.</p></article><article><b>05</b><h3>JV terms</h3><p>Document responsibilities, marketing rights, split, buyer ownership, and closing instructions.</p></article></div></section>

    <section className={styles.panel}><div className={styles.sectionHead}><div><span>JV PIPELINE</span><h2>Recent submissions</h2></div><a href="/owner/attention">Open Action Inbox →</a></div>{loading?<div className={styles.empty}>Loading JV submissions…</div>:recent.length?<div className={styles.list}>{recent.map(item=><article key={item.id}><div className={styles.rowHead}><div><span>JV #{item.id}</span><h3>{text(item.metadata?.name)}</h3></div><time>{item.created_at?new Date(item.created_at).toLocaleString():'—'}</time></div><p className={styles.contact}>{text(item.metadata?.email)} · {text(item.metadata?.phone)}</p><pre>{text(item.metadata?.message)}</pre><div className={styles.rowActions}><a href="/owner/deal-intelligence">Underwrite</a><a href="/owner/buyer-intake">Check buyers</a><a href="/owner/closing">Closing path</a></div></article>)}</div>:<div className={styles.empty}><b>No JV submissions yet.</b><span>The public JV form is live in source and will route submissions into this pipeline once deployed.</span></div>}</section>

    <section className={styles.policy}><h2>JV operating policy</h2><p>SAHJONY does not treat a submitted deal, claimed contract, ARV, repair estimate, buyer, or proposed split as verified. No joint marketing, seller representation, buyer commitment, assignment, or compensation obligation is created until the transaction is reviewed and written JV terms are approved.</p></section>
  </main>;
}

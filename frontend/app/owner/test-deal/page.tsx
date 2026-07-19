'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/test-deal';
const SESSION = 'sahjony_owner_session';

type Check = { name:string; ready:boolean; detail:string };
type Snapshot = { status:string; score:number; checks:Check[]; reason?:string; lead?:any; property?:any; matching_buyers?:number; verified_buyers?:number; deal_id?:number|null; safety?:Record<string,boolean>; detail?:string };
const empty:Snapshot = { status:'setup', score:0, checks:[] };

export default function TestDealPage(){
  const [token,setToken]=useState('');
  const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');

  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;
    if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const response=await fetch(`${API}/${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(response.status===401||response.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);
    return body;
  },[token]);

  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load rehearsal');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);

  async function run(){setLoading(true);setError('');setNotice('');try{const result=await request('run',{method:'POST',body:JSON.stringify({})});setData(result);setNotice(`Rehearsal complete: ${result.score||0}% readiness.`);}catch(e){setError(e instanceof Error?e.message:'Rehearsal failed');}finally{setLoading(false);}}

  const setup=data.status==='setup';
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>NON-DESTRUCTIVE VALIDATION</span><h1>Test Deal Rehearsal Center</h1><p>Verify underwriting, buyer coverage, contract readiness, and closing prerequisites without contacting sellers or sending binding documents.</p></div><div className={styles.actions}><button onClick={()=>void run()} disabled={loading||setup}>Run rehearsal</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/launch-validation">Launch Validation</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    {setup&&<div className={styles.notice}>API status: SETUP. Deploy the latest backend to activate the rehearsal engine.</div>}
    <section className={styles.metrics}><article><span>Status</span><strong>{data.status.toUpperCase()}</strong></article><article><span>Readiness</span><strong>{data.score||0}%</strong></article><article><span>Matching buyers</span><strong>{data.matching_buyers||0}</strong></article><article><span>Verified buyers</span><strong>{data.verified_buyers||0}</strong></article><article><span>Deal ID</span><strong>{data.deal_id||'—'}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>REHEARSAL CHECKS</span><h2>Lead-to-closing evidence</h2></div><strong>{data.checks.length}</strong></div><div className={styles.list}>{data.checks.length?data.checks.map((check,index)=><div key={`${check.name}-${index}`}><span><b>{check.name}</b><small>{check.detail}</small></span><strong>{check.ready?'PASS':'BLOCKED'}</strong></div>):<p>{data.reason||data.detail||'No rehearsal evidence is available yet.'}</p>}</div></section>
    {(data.lead||data.property)&&<section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>SELECTED RECORD</span><h2>{data.lead?.seller_name||'Lead'}</h2></div></div><p>{data.property?.address}, {data.property?.city} {data.property?.state} {data.property?.zip_code}</p><p>ARV: {data.property?.arv??'missing'} · Repairs: {data.property?.repairs??'missing'} · MAO: {data.property?.mao??'missing'}</p></section>}
    <div className={styles.notice}>Safety controls: no messages, calls, contracts, title orders, or closing actions are executed by this rehearsal.</div>
  </main>;
}

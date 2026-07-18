'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/acquisition-worker';
const SESSION = 'sahjony_owner_session';

type Run = { id:number; lead_id:number; property_id:number; status:string; current_step:string; attempts:number; last_error?:string; result:Record<string,any>; updated_at:string; completed_at?:string };
type Snapshot = { counts:Record<string,number>; provider_readiness:{attom:boolean;batchdata:boolean}; runs:Run[] };

export default function AcquisitionAutomationPage(){
  const [token,setToken]=useState('');
  const [data,setData]=useState<Snapshot>({counts:{},provider_readiness:{attom:false,batchdata:false},runs:[]});
  const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;
    if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const r=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await r.text(); let body:any={}; if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(r.status===401||r.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(r.status===404)throw new Error('Acquisition Worker API is not deployed yet. Redeploy the backend from latest main.');
    if(!r.ok)throw new Error(body.detail||`Request failed (${r.status})`);
    return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load automation');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function runPending(){setLoading(true);setError('');try{const r=await request('/run-pending',{method:'POST',body:JSON.stringify({limit:10})});setNotice(`Processed ${r.processed} lead(s).`);await load();}catch(e){setError(e instanceof Error?e.message:'Automation run failed');}finally{setLoading(false);}}
  async function retry(leadId:number){setLoading(true);setError('');try{await request(`/leads/${leadId}/run`,{method:'POST',body:JSON.stringify({force:true})});setNotice(`Lead #${leadId} reprocessed.`);await load();}catch(e){setError(e instanceof Error?e.message:'Lead retry failed');}finally{setLoading(false);}}
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>AUTONOMOUS ACQUISITION</span><h1>Acquisition Automation Console</h1><p>Run tenant-scoped property enrichment, seller enrichment, county verification queueing, and qualification review.</p></div><div className={styles.actions}><button onClick={()=>void runPending()} disabled={loading}>Run pending leads</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/acquisition">Lead Intake</a><a className={styles.linkButton} href="/owner/county">County Queue</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Completed</span><strong>{data.counts.completed||0}</strong></article><article><span>Waiting config</span><strong>{data.counts.waiting_configuration||0}</strong></article><article><span>Blocked</span><strong>{data.counts.blocked||0}</strong></article><article><span>ATTOM</span><strong>{data.provider_readiness.attom?'Ready':'Missing'}</strong></article><article><span>BatchData</span><strong>{data.provider_readiness.batchdata?'Ready':'Missing'}</strong></article><article><span>Runs</span><strong>{data.runs.length}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>WORKER HISTORY</span><h2>Lead automation runs</h2></div><strong>{data.runs.length}</strong></div><div className={styles.list}>{data.runs.length?data.runs.map(run=><div key={run.id}><span><b>Run #{run.id} · Lead #{run.lead_id}</b><small>{run.status} · step {run.current_step} · attempts {run.attempts}</small><small>{run.last_error||`ATTOM ${run.result?.attom?.status||'pending'} · BatchData ${run.result?.batchdata?.status||'pending'} · County case ${run.result?.county_case_id||'none'}`}</small></span><button onClick={()=>void retry(run.lead_id)} disabled={loading}>Retry</button></div>):<p>No automation runs yet. Import leads, then run pending leads.</p>}</div></section>
  </main>;
}

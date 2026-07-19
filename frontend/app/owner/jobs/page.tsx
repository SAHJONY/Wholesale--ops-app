'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/jobs';
const SESSION = 'sahjony_owner_session';

type Job = { id:number; job_type:string; status:string; priority:number; attempts:number; max_attempts:number; available_at:string; last_error?:string|null; payload:Record<string,unknown>; result:Record<string,unknown>; created_at:string; updated_at:string };
type Snapshot = { generated_at:string; counts:Record<string,number>; supported_job_types:string[]; scheduler?:{enabled:boolean;schedule:string;stale_lock_minutes:number;stale_running_jobs:number}; jobs:Job[]; status?:string };
const empty:Snapshot={generated_at:new Date().toISOString(),counts:{},supported_job_types:[],scheduler:{enabled:false,schedule:'*/15 * * * *',stale_lock_minutes:20,stale_running_jobs:0},jobs:[],status:'setup'};

export default function JobsPage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const response=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(response.status===401||response.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load jobs');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function runNext(){setLoading(true);setError('');setNotice('');try{const result=await request('/run-next',{method:'POST',body:JSON.stringify({limit:10})});setNotice(`Processed ${result.processed||0} job(s); recovered ${result.recovered_stale||0} stale job(s).`);await load();}catch(e){setError(e instanceof Error?e.message:'Unable to run jobs');}finally{setLoading(false);}}
  async function enqueueEvents(){setLoading(true);setError('');setNotice('');try{await request('',{method:'POST',body:JSON.stringify({job_type:'process_events',priority:80,payload:{limit:100}})});setNotice('Event-processing job queued.');await load();}catch(e){setError(e instanceof Error?e.message:'Unable to queue job');}finally{setLoading(false);}}
  async function retry(id:number){setLoading(true);setError('');try{await request(`/${id}/retry`,{method:'POST'});await load();}catch(e){setError(e instanceof Error?e.message:'Unable to retry job');}finally{setLoading(false);}}
  const c=data.counts; const scheduler=data.scheduler||empty.scheduler!;
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>AUTOMATION RELIABILITY</span><h1>Job Operations Center</h1><p>Run tenant-scoped work with persistent status, bounded retries, lease recovery, and dead-letter visibility.</p></div><div className={styles.actions}><button onClick={()=>void runNext()} disabled={loading}>Run next jobs</button><button onClick={()=>void enqueueEvents()} disabled={loading}>Queue event processing</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/system-health">System Health</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Scheduler</span><strong>{scheduler.enabled?'ON':'SETUP'}</strong></article><article><span>Queued</span><strong>{c.queued||0}</strong></article><article><span>Running</span><strong>{c.running||0}</strong></article><article><span>Retry</span><strong>{c.retry||0}</strong></article><article><span>Dead letter</span><strong>{c.dead_letter||0}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>SCHEDULER</span><h2>Worker cadence and leases</h2></div><strong>{scheduler.schedule}</strong></div><div className={styles.list}><div><span><b>Automatic execution</b><small>Runs every 15 minutes using CRON_SECRET authorization.</small></span><strong>{scheduler.enabled?'READY':'SETUP'}</strong></div><div><span><b>Stale lease recovery</b><small>Running jobs older than {scheduler.stale_lock_minutes} minutes are recovered.</small></span><strong>{scheduler.stale_running_jobs}</strong></div></div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>DURABLE QUEUE</span><h2>Recent jobs</h2></div><strong>{data.jobs.length}</strong></div><div className={styles.list}>{data.jobs.length?data.jobs.map(job=><div key={job.id}><span><b>#{job.id} · {job.job_type}</b><small>{job.status.toUpperCase()} · attempt {job.attempts}/{job.max_attempts} · priority {job.priority}{job.last_error?` · ${job.last_error}`:''}</small></span><span><strong>{job.status.toUpperCase()}</strong>{job.status==='dead_letter'&&<button onClick={()=>void retry(job.id)} disabled={loading}>Retry</button>}</span></div>):<p>{data.status==='setup'?'Jobs backend is in setup mode.':'No durable jobs have been queued.'}</p>}</div></section>
    <div className={styles.notice}>Supported jobs: {data.supported_job_types.length?data.supported_job_types.join(', '):'deploy backend to activate'}. High-impact outreach and contract actions remain approval-gated.</div>
  </main>;
}

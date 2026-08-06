'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

// The session cookie is HttpOnly and middleware attaches it to same-origin
// /api/* requests, so this page never sees or stores a token.
type Snapshot = {
  setup_mode?: boolean;
  instance: { deployment:string; environment:string; uptime_seconds:number; serverless_notice:string };
  database: { status:string; latency_ms:number|null; error_type?:string };
  requests: { sample_size:number; error_count:number; slow_count:number; average_duration_ms:number; slow_threshold_ms:number; status_counts:Record<string,number>; top_routes:Array<{path:string;count:number}> };
  recent_errors:Array<Record<string,unknown>>;
  recent_slow_requests:Array<Record<string,unknown>>;
};

const empty: Snapshot = {
  instance:{deployment:'unknown',environment:'unknown',uptime_seconds:0,serverless_notice:''},
  database:{status:'unknown',latency_ms:null},
  requests:{sample_size:0,error_count:0,slow_count:0,average_duration_ms:0,slow_threshold_ms:1500,status_counts:{},top_routes:[]},
  recent_errors:[],recent_slow_requests:[],
};

type Version={status:string;frontend_commit:string|null;backend_commit:string|null;detail:string|null};

export default function SystemHealthPage(){
  const [data,setData]=useState<Snapshot>(empty);
  const [version,setVersion]=useState<Version|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);

  const load=useCallback(async()=>{
    setLoading(true);setError('');
    // Deliberately not awaited with the snapshot: a drifted or unreachable
    // backend is exactly when this page must still render.
    void fetch('/api/version',{cache:'no-store'}).then(r=>r.json()).then(setVersion).catch(()=>setVersion(null));
    try{
      const response=await fetch('/api/observability/snapshot',{cache:'no-store',credentials:'same-origin'});
      const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
      if(response.status===401||response.status===403){location.replace('/login?returnTo=/owner/system-health');return;}
      if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);
      setData(body);
    }catch(e){setError(e instanceof Error?e.message:'Unable to load system health');}
    finally{setLoading(false);}
  },[]);

  useEffect(()=>{void load();},[load]);

  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>SYSTEM RELIABILITY</span><h1>System Health</h1><p>Inspect deployment identity, database reachability, request latency, slow endpoints, and server errors.</p></div><div className={styles.actions}><button onClick={()=>void load()} disabled={loading}>{loading?'Checking…':'Refresh'}</button><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {version?.status==='drifted'&&<div className={styles.error}>
      Frontend and backend are running different commits. One of them did not ship, so a merged fix
      may not be live. Frontend {version.frontend_commit?.slice(0,7)} · backend {version.backend_commit?.slice(0,7)}.
    </div>}
    {version?.status==='backend_unreachable'&&<div className={styles.error}>{version.detail}</div>}
    {version?.status==='unknown'&&version.detail&&<div className={styles.cycleSummary}>{version.detail}</div>}
    {data.setup_mode&&<div className={styles.notice}>Observability API is not deployed yet. The dashboard is in setup mode.</div>}
    {error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Database</span><strong>{data.database.status.toUpperCase()}</strong></article><article><span>DB latency</span><strong>{data.database.latency_ms==null?'—':`${data.database.latency_ms} ms`}</strong></article><article><span>Requests sampled</span><strong>{data.requests.sample_size}</strong></article><article><span>Server errors</span><strong>{data.requests.error_count}</strong></article><article><span>Slow requests</span><strong>{data.requests.slow_count}</strong></article><article><span>Average latency</span><strong>{data.requests.average_duration_ms} ms</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>DEPLOYMENT</span><h2>Active instance</h2></div><strong>{data.instance.environment}</strong></div><div className={styles.list}><div><span><b>Backend commit</b><small>{data.instance.deployment}</small></span><span className={version?.status==='in_sync'?styles.healthy:styles.idle}>{version?.status==='in_sync'?'in sync':version?.status?.replace(/_/g,' ')??'unverified'}</span></div><div><span><b>Frontend commit</b><small>{version?.frontend_commit??'not reported outside Vercel'}</small></span></div><div><span><b>Uptime</b><small>{data.instance.uptime_seconds} seconds</small></span></div><div><span><b>Serverless scope</b><small>{data.instance.serverless_notice}</small></span></div></div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>TRAFFIC</span><h2>Top routes</h2></div><strong>{data.requests.top_routes.length}</strong></div><div className={styles.list}>{data.requests.top_routes.length?data.requests.top_routes.map(item=><div key={item.path}><span><b>{item.path}</b><small>{item.count} requests</small></span></div>):<p>No request telemetry collected on this instance yet.</p>}</div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>INCIDENTS</span><h2>Recent server errors</h2></div><strong>{data.recent_errors.length}</strong></div><div className={styles.list}>{data.recent_errors.length?data.recent_errors.map((item:any,index)=><div key={`${item.request_id||index}`}><span><b>{item.method} {item.path}</b><small>{item.status_code} · {item.duration_ms} ms · request {item.request_id}</small></span></div>):<p>No server errors recorded on this instance.</p>}</div></section>
  </main>;
}

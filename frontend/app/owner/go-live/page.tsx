'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/go-live';
const SESSION = 'sahjony_owner_session';

type Check = { name:string; category:string; ready:boolean; severity:string; detail:string; action:string };
type Snapshot = {
  status:string; score:number; blocker_count:number; checks:Check[]; missing_routes:string[];
  providers:Record<string,boolean>; workspace:Record<string,number>; jobs:Record<string,number>;
  owner_pages:string[]; launch_policy:{automatic_production_launch:boolean;owner_approval_required:boolean;message:string};
};

const empty:Snapshot={status:'setup',score:0,blocker_count:0,checks:[],missing_routes:[],providers:{},workspace:{leads:0,properties:0,buyers:0,deals:0},jobs:{},owner_pages:[],launch_policy:{automatic_production_launch:false,owner_approval_required:true,message:'Deploy the backend to activate readiness checks.'}};
const remediation:Record<string,string>={infrastructure:'/owner/system-health',deployment:'/owner/system-health',integrations:'/owner/integrations',continuity:'/owner/continuity',automation:'/owner/jobs',business:'/owner'};

export default function GoLivePage(){
  const [token,setToken]=useState('');
  const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');

  const load=useCallback(async(override?:string)=>{
    const active=override||token;
    if(!active){location.replace('/owner-access');return;}
    setLoading(true);setError('');
    try{
      const response=await fetch(API,{cache:'no-store',headers:{Authorization:`Bearer ${active}`}});
      const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
      if(response.status===401||response.status===403){location.replace('/owner-access');return;}
      if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);
      setData(body);
    }catch(e){setError(e instanceof Error?e.message:'Unable to load launch readiness');}
    finally{setLoading(false);}
  },[token]);

  useEffect(()=>{const stored='cookie-session';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);

  const blockers=useMemo(()=>data.checks.filter(item=>!item.ready),[data.checks]);
  const ready=useMemo(()=>data.checks.filter(item=>item.ready),[data.checks]);

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>PRODUCTION LAUNCH</span><h1>Go-Live Command Center</h1><p>Measure real launch readiness across infrastructure, integrations, automation, continuity, and the complete wholesale workflow.</p></div>
      <div className={styles.actions}><button onClick={()=>void load()} disabled={loading}>Run readiness check</button><a className={styles.linkButton} href="/owner/integrations">Integrations</a><a className={styles.linkButton} href="/owner/system-health">System Health</a><a className={styles.linkButton} href="/owner">Control Plane</a></div>
    </header>

    {error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}>
      <article><span>Launch status</span><strong>{data.status.toUpperCase()}</strong></article>
      <article><span>Readiness score</span><strong>{data.score}%</strong></article>
      <article><span>Blockers</span><strong>{data.blocker_count}</strong></article>
      <article><span>Checks passed</span><strong>{ready.length}/{data.checks.length}</strong></article>
      <article><span>Dead letters</span><strong>{data.jobs.dead_letter||0}</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>BLOCKERS</span><h2>Required actions before launch</h2></div><strong>{blockers.length}</strong></div>
      <div className={styles.list}>{blockers.length?blockers.map((item,index)=><div key={`${item.name}-${index}`}><span><b>{item.name}</b><small>{item.severity.toUpperCase()} · {item.detail} · {item.action}</small></span><a className={styles.linkButton} href={remediation[item.category]||'/owner'}>{item.category.toUpperCase()}</a></div>):<p>No readiness blockers detected.</p>}</div>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>BUSINESS EVIDENCE</span><h2>Workspace operating data</h2></div><strong>{Object.values(data.workspace).reduce((a,b)=>a+b,0)}</strong></div>
      <div className={styles.list}>{Object.entries(data.workspace).map(([name,value])=><div key={name}><span><b>{name.replaceAll('_',' ')}</b><small>Tenant-scoped production record count</small></span><strong>{value}</strong></div>)}</div>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVIDERS</span><h2>Connection readiness</h2></div><strong>{Object.values(data.providers).filter(Boolean).length}/{Object.keys(data.providers).length}</strong></div>
      <div className={styles.list}>{Object.entries(data.providers).map(([name,value])=><div key={name}><span><b>{name.replaceAll('_',' ')}</b><small>{value?'Credential requirements detected':'Provider credentials incomplete'}</small></span><strong>{value?'READY':'SETUP'}</strong></div>)}</div>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PASSED CONTROLS</span><h2>Verified readiness</h2></div><strong>{ready.length}</strong></div>
      <div className={styles.list}>{ready.length?ready.map((item,index)=><div key={`${item.name}-${index}`}><span><b>{item.name}</b><small>{item.detail}</small></span><strong>READY</strong></div>):<p>No checks have passed yet.</p>}</div>
    </section>

    <div className={styles.notice}>{data.launch_policy.message}</div>
  </main>;
}

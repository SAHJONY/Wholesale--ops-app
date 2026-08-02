'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/continuity';
const SESSION = 'sahjony_owner_session';

type Drill = { id:number; status:string; environment:string; recovery_minutes?:number|null; evidence_reference?:string|null; notes?:string|null; recorded_at:string };
type Snapshot = {
  status:string; provider:string; database:{ok:boolean;error?:string|null};
  objectives:{rpo_hours:number;rto_hours:number;restore_drill_interval_days:number};
  controls:Record<string,boolean>;
  summary:{controls_ready:number;controls_total:number;restore_drill_due:boolean;last_successful_drill_at?:string|null};
  drills:Drill[]; safety:{automatic_restore_enabled:boolean;message:string};
};

const empty:Snapshot={status:'setup',provider:'unknown',database:{ok:false},objectives:{rpo_hours:24,rto_hours:8,restore_drill_interval_days:90},controls:{},summary:{controls_ready:0,controls_total:0,restore_drill_due:true},drills:[],safety:{automatic_restore_enabled:false,message:'Continuity controls are not active yet.'}};

export default function ContinuityPage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const response=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(response.status===401||response.status===403){location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load continuity controls');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored='cookie-session';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function recordDrill(){
    const recovery=prompt('Recovery time in minutes for the staging drill:','30'); if(recovery===null)return;
    const status=prompt('Drill result: passed, partial, or failed','passed'); if(!status)return;
    setLoading(true);setError('');setNotice('');
    try{await request('/restore-drills',{method:'POST',body:JSON.stringify({status,environment:'staging',recovery_minutes:Number(recovery)})});setNotice('Restore drill recorded.');await load();}
    catch(e){setError(e instanceof Error?e.message:'Unable to record drill');}finally{setLoading(false);}
  }
  const controls=Object.entries(data.controls);
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>BUSINESS CONTINUITY</span><h1>Backup & Recovery Center</h1><p>Verify backup readiness, recovery objectives, and restore-drill evidence without automating destructive production restores.</p></div><div className={styles.actions}><button onClick={()=>void recordDrill()} disabled={loading}>Record staging drill</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/system-health">System Health</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Status</span><strong>{data.status.toUpperCase()}</strong></article><article><span>Controls ready</span><strong>{data.summary.controls_ready}/{data.summary.controls_total}</strong></article><article><span>RPO</span><strong>{data.objectives.rpo_hours}h</strong></article><article><span>RTO</span><strong>{data.objectives.rto_hours}h</strong></article><article><span>Drill due</span><strong>{data.summary.restore_drill_due?'YES':'NO'}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>CONTROLS</span><h2>Recovery readiness</h2></div><strong>{data.provider.toUpperCase()}</strong></div><div className={styles.list}>{controls.length?controls.map(([name,ready])=><div key={name}><span><b>{name.replaceAll('_',' ')}</b><small>{ready?'Ready':'Action required'}</small></span><strong>{ready?'READY':'SETUP'}</strong></div>):<p>Continuity backend is in setup mode.</p>}</div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>RESTORE DRILLS</span><h2>Evidence history</h2></div><strong>{data.drills.length}</strong></div><div className={styles.list}>{data.drills.length?data.drills.map(d=><div key={d.id}><span><b>{d.status.toUpperCase()} · {d.environment}</b><small>{d.recovery_minutes!=null?`${d.recovery_minutes} minutes · `:''}{new Date(d.recorded_at).toLocaleString()}</small></span><strong>{d.status.toUpperCase()}</strong></div>):<p>No restore drill has been recorded.</p>}</div></section>
    <div className={styles.notice}>{data.safety.message}</div>
  </main>;
}

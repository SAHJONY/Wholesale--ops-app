'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API='/api/launch-validation';
const SESSION='sahjony_owner_session';

type Result={name:string;passed:boolean;severity:string;detail:string;remediation:string};
type Report={status:string;score:number;summary:{passed:number;failed:number;critical_failures:number;high_failures:number};results:Result[];workspace:Record<string,number>;safety:Record<string,boolean>};
type Snapshot={latest_report:Report|null;latest_run_at:string|null;status?:string};

export default function LaunchValidationPage(){
  const [token,setToken]=useState('');const [data,setData]=useState<Snapshot>({latest_report:null,latest_run_at:null});
  const [loading,setLoading]=useState(true);const [error,setError]=useState('');const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const response=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(response.status===401||response.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load validation report');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function run(){setLoading(true);setError('');setNotice('');try{const report=await request('/run',{method:'POST',body:'{}'});setData({latest_report:report,latest_run_at:new Date().toISOString()});setNotice(`Validation completed: ${report.status.toUpperCase()} · ${report.score}%`);}catch(e){setError(e instanceof Error?e.message:'Unable to run validation');}finally{setLoading(false);}}
  const r=data.latest_report;
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>PRODUCTION EVIDENCE</span><h1>Launch Validation Center</h1><p>Execute a non-destructive production rehearsal covering routes, providers, tenant integrity, Texas exclusion, underwriting, buyers, and queue health.</p></div><div className={styles.actions}><button onClick={()=>void run()} disabled={loading}>Run validation</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/go-live">Go-Live Center</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Status</span><strong>{r?.status?.toUpperCase()||'NOT RUN'}</strong></article><article><span>Score</span><strong>{r?`${r.score}%`:'--'}</strong></article><article><span>Passed</span><strong>{r?.summary.passed||0}</strong></article><article><span>Critical failures</span><strong>{r?.summary.critical_failures||0}</strong></article><article><span>High failures</span><strong>{r?.summary.high_failures||0}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>EXECUTABLE CHECKS</span><h2>Validation evidence</h2></div><strong>{r?.results.length||0}</strong></div><div className={styles.list}>{r?.results?.length?r.results.map((item,index)=><div key={`${item.name}-${index}`}><span><b>{item.name}</b><small>{item.severity.toUpperCase()} · {item.detail}{!item.passed&&item.remediation?` · ${item.remediation}`:''}</small></span><strong>{item.passed?'PASS':'FAIL'}</strong></div>):<p>No launch validation has been run.</p>}</div></section>
    <div className={styles.notice}>This rehearsal is non-destructive. It does not send seller messages, contracts, or payments. Texas records are treated as a critical launch failure.</div>
  </main>;
}

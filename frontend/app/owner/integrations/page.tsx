'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const HUB_API = '/api/integration-hub';
const RELIABILITY_API = '/api/integration-reliability';
const SESSION = 'sahjony_owner_session';

type Provider = { id:string; name:string; category:string; tier:string; state:string; capabilities:string[]; missing_variables:string[]; configured_variables:string[]; last_check?:{status:string;latency_ms?:number;message?:string;checked_at:string}|null };
type Snapshot = { summary:{providers:number;configured:number;partial:number;not_configured:number}; workflow_readiness:Record<string,boolean>; providers:Provider[]; runs:{id:number;status:string;providers_checked:number;providers_ready:number;providers_blocked:number;started_at:string}[] };
type Alert = { id:number;provider_id:string;status:string;severity:string;failure_streak:number;affected_workflows:string[];summary:string;details:Record<string,unknown>;last_detected_at:string;resolved_at?:string };
type Reliability = { summary:{open:number;critical:number;resolved:number};alerts:Alert[] };
const empty:Snapshot={summary:{providers:0,configured:0,partial:0,not_configured:0},workflow_readiness:{},providers:[],runs:[]};
const emptyReliability:Reliability={summary:{open:0,critical:0,resolved:0},alerts:[]};

export default function IntegrationOperationsPage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty); const [reliability,setReliability]=useState<Reliability>(emptyReliability);
  const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(base:string,path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const r=await fetch(`${base}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await r.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(r.status===401||r.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!r.ok)throw new Error(body.detail||`Request failed (${r.status})`);return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{const [hub,rel]=await Promise.all([request(HUB_API,'/snapshot',{},override),request(RELIABILITY_API,'/snapshot',{},override)]);setData(hub);setReliability(rel);}catch(e){setError(e instanceof Error?e.message:'Unable to load integrations');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function checkAll(){setLoading(true);setError('');setNotice('');try{const result=await request(RELIABILITY_API,'/run-now',{method:'POST',body:'{}'});setNotice(`Reliability run #${result.run_id}: ${result.alerts_opened} alerts opened, ${result.alerts_resolved} resolved.`);await load();}catch(e){setError(e instanceof Error?e.message:'Health check failed');}finally{setLoading(false);}}
  const workflows=Object.entries(data.workflow_readiness); const openAlerts=reliability.alerts.filter(a=>a.status==='open');
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>INTEGRATION OPERATIONS</span><h1>Production Integration Hub</h1><p>Control provider readiness, endpoint reliability, workflow impact, and recovery from one place.</p></div><div className={styles.actions}><button onClick={()=>void checkAll()} disabled={loading}>Run reliability checks</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/attention">Attention Center</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Providers</span><strong>{data.summary.providers}</strong></article><article><span>Configured</span><strong>{data.summary.configured}</strong></article><article><span>Open alerts</span><strong>{reliability.summary.open}</strong></article><article><span>Critical</span><strong>{reliability.summary.critical}</strong></article><article><span>Resolved</span><strong>{reliability.summary.resolved}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>RELIABILITY</span><h2>Provider alerts</h2></div><strong>{openAlerts.length}</strong></div><div className={styles.list}>{openAlerts.length?openAlerts.map(a=><div key={a.id}><span><b>{a.provider_id} · {a.severity.toUpperCase()}</b><small>{a.summary} · failure streak {a.failure_streak}</small><small>Affects: {a.affected_workflows.join(', ')||'No mapped workflow'} · last detected {new Date(a.last_detected_at).toLocaleString()}</small></span><strong>{a.status.toUpperCase()}</strong></div>):<p>No active provider reliability alerts.</p>}</div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>WORKFLOWS</span><h2>Operational readiness</h2></div><strong>{workflows.filter(([,ready])=>ready).length}/{workflows.length}</strong></div><div className={styles.list}>{workflows.map(([name,ready])=><div key={name}><span><b>{name.replaceAll('_',' ')}</b><small>{ready?'Ready for controlled production use':'Blocked by missing provider configuration'}</small></span><strong>{ready?'READY':'BLOCKED'}</strong></div>)}</div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVIDERS</span><h2>Provider control plane</h2></div><strong>{data.providers.length}</strong></div><div className={styles.list}>{data.providers.map(p=><div key={p.id}><span><b>{p.name}</b><small>{p.category} · {p.tier} · {p.state}</small><small>{p.capabilities.join(', ')}</small><small>{p.last_check?`${p.last_check.status}${p.last_check.latency_ms!=null?` · ${p.last_check.latency_ms}ms`:''} · ${p.last_check.message||''}`:`Missing: ${p.missing_variables.join(', ')||'none'}`}</small></span><strong>{p.state==='configured'||p.state==='available_public_or_manual'?'READY':p.state==='partial'?'PARTIAL':'SETUP'}</strong></div>)}</div></section>
  </main>;
}

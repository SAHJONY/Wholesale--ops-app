'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/national-intelligence';
const SESSION = 'sahjony_owner_session';

type PropertyScore = {
  id:number; lead_id:number; property_id:number; market:string; opportunity_score:number;
  distress_score:number; equity_score:number; buyer_demand_score:number; data_confidence:number;
  ownership_verified:boolean; projected_assignment_fee?:number; reasons:string[]; warnings:string[];
};
type Market = { market:string; properties:number; high_priority:number; average_score:number; projected_fees:number };
type Run = { id:number; status:string; trigger:string; properties_scored:number; high_priority_count:number; started_at:string };
type Snapshot = {
  status?:string; detail?:string;
  summary:{properties:number;high_priority:number;ownership_verified:number;projected_assignment_fees:number;average_opportunity_score:number};
  properties:PropertyScore[]; markets:Market[]; runs:Run[];
};
const empty:Snapshot={status:'setup',summary:{properties:0,high_priority:0,ownership_verified:0,projected_assignment_fees:0,average_opportunity_score:0},properties:[],markets:[],runs:[]};

function normalize(value:any):Snapshot {
  const summary=value?.summary&&typeof value.summary==='object'?value.summary:{};
  return {
    status:typeof value?.status==='string'?value.status:'active',
    detail:typeof value?.detail==='string'?value.detail:undefined,
    summary:{
      properties:Number(summary.properties||0),
      high_priority:Number(summary.high_priority||0),
      ownership_verified:Number(summary.ownership_verified||0),
      projected_assignment_fees:Number(summary.projected_assignment_fees||0),
      average_opportunity_score:Number(summary.average_opportunity_score||0),
    },
    properties:Array.isArray(value?.properties)?value.properties.map((item:any)=>({...item,reasons:Array.isArray(item?.reasons)?item.reasons:[],warnings:Array.isArray(item?.warnings)?item.warnings:[]})):[],
    markets:Array.isArray(value?.markets)?value.markets:[],
    runs:Array.isArray(value?.runs)?value.runs:[],
  };
}

export default function NationalIntelligencePage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const r=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await r.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(r.status===401||r.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(r.status===404)throw new Error('National Intelligence API is not deployed yet. Redeploy the backend from latest main.');
    if(!r.ok)throw new Error(body.detail||`Request failed (${r.status})`);return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(normalize(await request('/snapshot',{},override)));}catch(e){setData(empty);setError(e instanceof Error?e.message:'Unable to load national intelligence');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function refresh(){setLoading(true);setError('');setNotice('');try{const r=await request('/refresh',{method:'POST',body:JSON.stringify({limit:2000,trigger:'owner_dashboard'})});setNotice(`Run #${r.run_id}: ${r.properties_scored} properties scored; ${r.high_priority_count} high priority.`);await load();}catch(e){setError(e instanceof Error?e.message:'Refresh failed');}finally{setLoading(false);}}
  const money=(v?:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(v||0);
  const setup=data.status==='setup';
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>NATIONAL INTELLIGENCE</span><h1>Property Intelligence Network</h1><p>Rank opportunities using verified property evidence, distress, equity proxy, buyer demand, and data confidence.</p></div><div className={styles.actions}><button onClick={()=>void refresh()} disabled={loading||setup}>Refresh intelligence</button><button onClick={()=>void load()} disabled={loading}>Reload</button><a className={styles.linkButton} href="/owner/acquisition-automation">Acquisition Worker</a><a className={styles.linkButton} href="/owner/intelligence">Canonical Intelligence</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}{setup&&<div className={styles.notice}>API status: SETUP. {data.detail||'Redeploy the latest backend to initialize the intelligence database objects.'}</div>}
    <section className={styles.metrics}><article><span>Properties scored</span><strong>{data.summary.properties}</strong></article><article><span>High priority</span><strong>{data.summary.high_priority}</strong></article><article><span>Ownership verified</span><strong>{data.summary.ownership_verified}</strong></article><article><span>Average score</span><strong>{data.summary.average_opportunity_score}</strong></article><article><span>Projected fees</span><strong>{money(data.summary.projected_assignment_fees)}</strong></article></section>
    <section className={styles.grid}><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>MARKETS</span><h2>Market rankings</h2></div><strong>{data.markets.length}</strong></div><div className={styles.list}>{data.markets.length?data.markets.map(m=><div key={m.market}><span><b>{m.market}</b><small>{m.properties} properties · {m.high_priority} high priority · average {m.average_score}</small><small>{money(m.projected_fees)} projected assignment spread</small></span></div>):<p>Run intelligence refresh to score workspace properties.</p>}</div></article>
    <article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>OPPORTUNITIES</span><h2>Top properties</h2></div><strong>{data.properties.length}</strong></div><div className={styles.list}>{data.properties.length?data.properties.slice(0,100).map(p=><div key={p.id}><span><b>Property #{p.property_id} · Score {p.opportunity_score}</b><small>{p.market} · distress {p.distress_score} · equity {p.equity_score} · demand {p.buyer_demand_score}</small><small>{p.ownership_verified?'County-verified owner':'Ownership pending'} · confidence {p.data_confidence} · {money(p.projected_assignment_fee)}</small><small>{p.reasons.join(' · ')||p.warnings[0]||'More verified evidence required'}</small></span></div>):<p>No property scores yet.</p>}</div></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>REFRESH HISTORY</span><h2>Intelligence runs</h2></div><strong>{data.runs.length}</strong></div><div className={styles.list}>{data.runs.map(r=><div key={r.id}><span><b>Run #{r.id} · {r.status}</b><small>{r.trigger} · {r.properties_scored} scored · {r.high_priority_count} high priority · {new Date(r.started_at).toLocaleString()}</small></span></div>)}</div></section>
  </main>;
}

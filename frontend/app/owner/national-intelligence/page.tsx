'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/national-intelligence';
const SESSION = 'sahjony_owner_session';

type Snapshot = {
  summary: { properties:number; high_priority:number; ownership_verified:number; projected_assignment_fees:number; average_opportunity_score:number };
  markets: Array<{ market:string; properties:number; high_priority:number; average_score:number; projected_fees:number }>;
  properties: Array<{ id:number; property_id:number; market:string; opportunity_score:number; distress_score:number; equity_score:number; buyer_demand_score:number; data_confidence:number; ownership_verified:boolean; projected_assignment_fee?:number; reasons:string[]; warnings:string[] }>;
  runs: Array<{ id:number; status:string; trigger:string; properties_scored:number; high_priority_count:number; started_at:string }>;
};

const empty: Snapshot = { summary:{properties:0,high_priority:0,ownership_verified:0,projected_assignment_fees:0,average_opportunity_score:0}, markets:[], properties:[], runs:[] };

export default function NationalIntelligencePage() {
  const [token,setToken]=useState('');
  const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');

  const request=useCallback(async(path:string, options:RequestInit={}, override?:string)=>{
    const active=override||token;
    if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const response=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text();
    let body:any={};
    if(text){try{body=JSON.parse(text);}catch{body={detail:text};}}
    if(response.status===401||response.status===403){location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);
    return body;
  },[token]);

  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load intelligence');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored='cookie-session';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);

  async function refresh(){setLoading(true);setError('');try{const result=await request('/refresh',{method:'POST',body:JSON.stringify({limit:2000,trigger:'owner_dashboard'})});setNotice(`Run #${result.run_id}: ${result.properties_scored} properties scored.`);await load();}catch(e){setError(e instanceof Error?e.message:'Refresh failed');}finally{setLoading(false);}}
  const money=(value?:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value||0);

  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>NATIONAL INTELLIGENCE</span><h1>Property Intelligence Network</h1><p>Rank opportunities using verified evidence, distress, equity, buyer demand, and data confidence.</p></div><div className={styles.actions}><button onClick={()=>void refresh()} disabled={loading}>Refresh intelligence</button><button onClick={()=>void load()} disabled={loading}>Reload</button><a className={styles.linkButton} href="/owner/acquisition-automation">Acquisition Worker</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Properties scored</span><strong>{data.summary.properties}</strong></article><article><span>High priority</span><strong>{data.summary.high_priority}</strong></article><article><span>Ownership verified</span><strong>{data.summary.ownership_verified}</strong></article><article><span>Average score</span><strong>{data.summary.average_opportunity_score}</strong></article><article><span>Projected fees</span><strong>{money(data.summary.projected_assignment_fees)}</strong></article></section>
    <section className={styles.grid}><article className={styles.card}><div className={styles.cardHeader}><h2>Market rankings</h2><strong>{data.markets.length}</strong></div><div className={styles.list}>{data.markets.length?data.markets.map(m=><div key={m.market}><span><b>{m.market}</b><small>{m.properties} properties · {m.high_priority} high priority · average {m.average_score}</small><small>{money(m.projected_fees)} projected spread</small></span></div>):<p>Run a refresh to score markets.</p>}</div></article>
    <article className={styles.card}><div className={styles.cardHeader}><h2>Top properties</h2><strong>{data.properties.length}</strong></div><div className={styles.list}>{data.properties.length?data.properties.slice(0,100).map(p=><div key={p.id}><span><b>Property #{p.property_id} · Score {p.opportunity_score}</b><small>{p.market} · distress {p.distress_score} · equity {p.equity_score} · demand {p.buyer_demand_score}</small><small>{p.ownership_verified?'County-verified owner':'Ownership pending'} · confidence {p.data_confidence} · {money(p.projected_assignment_fee)}</small><small>{p.reasons.join(' · ')||p.warnings[0]||'More evidence required'}</small></span></div>):<p>No property scores yet.</p>}</div></article></section>
  </main>;
}

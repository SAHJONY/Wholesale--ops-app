'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API_URL = '/api/event-core';
const SESSION_STORAGE = 'sahjony_owner_session';
const SIGN_IN_URL = '/owner-access';

type EventItem = { id:number; event_type:string; aggregate_type:string; aggregate_id?:number; status:string; attempts:number; last_error?:string; correlation_id:string; created_at:string };
type Subscription = { id:number; subscriber_name:string; event_type:string; handler_name:string; is_active:boolean; max_attempts:number };
type Snapshot = { generated_at:string; health:string; event_counts:Record<string,number>; delivery_counts:Record<string,number>; events:EventItem[]; subscriptions:Subscription[] };
const empty:Snapshot={generated_at:'',health:'unknown',event_counts:{},delivery_counts:{},events:[],subscriptions:[]};

export default function EventCorePage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty); const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;
    if(!active){window.location.replace(SIGN_IN_URL);throw new Error('Owner session required');}
    let r:Response;
    try {
      r=await fetch(`${API_URL}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    } catch(e) {
      throw new Error(e instanceof Error ? `Event Center network error: ${e.message}` : 'Event Center network error');
    }
    const text=await r.text();
    let body:any={};
    if(text){try{body=JSON.parse(text);}catch{body={detail:text};}}
    if(r.status===401||r.status===403){localStorage.removeItem(SESSION_STORAGE);window.location.replace(SIGN_IN_URL);throw new Error('Owner session expired');}
    if(!r.ok)throw new Error(typeof body.detail==='string'?body.detail:`Request failed (${r.status})`);
    return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load event core');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION_STORAGE)||'';if(!stored){window.location.replace(SIGN_IN_URL);return;}setToken(stored);void load(stored);},[load]);
  async function process(){setLoading(true);setError('');try{const r=await request('/process',{method:'POST',body:JSON.stringify({limit:100})});setNotice(`Processed ${r.processed}; completed ${r.completed}; failed ${r.failed}.`);await load();}catch(e){setError(e instanceof Error?e.message:'Unable to process events');}finally{setLoading(false);}}
  async function replay(id:number){setLoading(true);setError('');try{await request(`/events/${id}/replay`,{method:'POST',body:'{}'});setNotice(`Event #${id} queued for replay.`);await load();}catch(e){setError(e instanceof Error?e.message:'Unable to replay event');}finally{setLoading(false);}}
  async function toggle(s:Subscription){setLoading(true);setError('');try{await request(`/subscriptions/${s.id}`,{method:'PATCH',body:JSON.stringify({is_active:!s.is_active})});await load();}catch(e){setError(e instanceof Error?e.message:'Unable to update subscription');}finally{setLoading(false);}}
  return <main className={styles.page}><header className={styles.header}><div><span className={styles.eyebrow}>AUTONOMOUS CORE</span><h1>Event Operations Center</h1><p>Durable business events, subscribers, retries, and dead-letter recovery.</p></div><div className={styles.actions}><button onClick={()=>void process()} disabled={loading}>Process events</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner">Control Plane</a><a className={styles.linkButton} href="/owner/disposition">Disposition</a><a className={styles.linkButton} href="/owner/closing">Closing</a></div></header>{notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}<section className={styles.metrics}><article><span>Health</span><strong>{data.health}</strong></article><article><span>Pending</span><strong>{data.event_counts.pending||0}</strong></article><article><span>Completed</span><strong>{data.event_counts.completed||0}</strong></article><article><span>Retries</span><strong>{data.event_counts.retry||0}</strong></article><article><span>Dead letters</span><strong>{data.event_counts.dead_letter||0}</strong></article><article><span>Deliveries</span><strong>{Object.values(data.delivery_counts).reduce((a,b)=>a+b,0)}</strong></article></section><section className={styles.grid}><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>SUBSCRIBERS</span><h2>AI department subscriptions</h2></div><strong>{data.subscriptions.length}</strong></div><div className={styles.list}>{data.subscriptions.map(s=><div key={s.id}><span><b>{s.subscriber_name}</b><small>{s.event_type} → {s.handler_name}</small></span><button onClick={()=>void toggle(s)} disabled={loading}>{s.is_active?'Disable':'Enable'}</button></div>)}</div></article><article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>EVENT STREAM</span><h2>Latest business events</h2></div><strong>{data.events.length}</strong></div><div className={styles.list}>{data.events.length?data.events.map(e=><div key={e.id}><span><b>#{e.id} · {e.event_type}</b><small>{e.aggregate_type} #{e.aggregate_id||'—'} · {e.status} · attempts {e.attempts}</small><small>{e.last_error||`Correlation ${e.correlation_id}`}</small></span>{(e.status==='dead_letter'||e.status==='retry')&&<button onClick={()=>void replay(e.id)} disabled={loading}>Replay</button>}</div>):<p>No events yet. Existing workflows can emit events as they are connected.</p>}</div></article></section></main>;
}

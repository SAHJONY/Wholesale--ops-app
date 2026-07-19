'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../owner.module.css';

const API='/api/audit';
const SESSION='sahjony_owner_session';
type Item={id:number;category:string;activity_type:string;summary:string;user?:{name:string;email:string}|null;lead_id?:number|null;deal_id?:number|null;created_at:string};
type Snapshot={generated_at:string;window_days:number;total:number;category_counts:Record<string,number>;activity_type_counts:Record<string,number>;items:Item[];status?:string;retention_note:string};
const empty:Snapshot={generated_at:new Date().toISOString(),window_days:30,total:0,category_counts:{},activity_type_counts:{},items:[],status:'setup',retention_note:''};

export default function AuditPage(){
  const [token,setToken]=useState('');const [data,setData]=useState<Snapshot>(empty);const [days,setDays]=useState(30);const [category,setCategory]=useState('');
  const [loading,setLoading]=useState(true);const [error,setError]=useState('');
  const request=useCallback(async(path:string,override?:string)=>{const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const r=await fetch(`${API}${path}`,{cache:'no-store',headers:{Authorization:`Bearer ${active}`}});const text=await r.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(r.status===401||r.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}if(!r.ok)throw new Error(body.detail||`Request failed (${r.status})`);return body;},[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{const q=new URLSearchParams({days:String(days)});if(category)q.set('category',category);setData(await request(`/snapshot?${q}`,override));}catch(e){setError(e instanceof Error?e.message:'Unable to load audit trail');}finally{setLoading(false);}},[request,days,category]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  const categories=useMemo(()=>['',...Object.keys(data.category_counts).sort()],[data.category_counts]);
  async function exportCsv(){const q=new URLSearchParams({days:String(days)});if(category)q.set('category',category);const r=await fetch(`${API}/export.csv?${q}`,{headers:{Authorization:`Bearer ${token}`}});if(!r.ok){setError('Unable to export audit CSV');return;}const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='sahjony-audit.csv';a.click();URL.revokeObjectURL(url);}
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>GOVERNANCE</span><h1>Audit & Accountability Center</h1><p>Review tenant-scoped security, approvals, automation, closing, and data activity from the existing operational ledger.</p></div><div className={styles.actions}><button onClick={()=>void exportCsv()} disabled={loading||!token}>Export CSV</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/security">Security</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Events</span><strong>{data.total}</strong></article><article><span>Security</span><strong>{data.category_counts.security||0}</strong></article><article><span>Approvals</span><strong>{data.category_counts.approval||0}</strong></article><article><span>Automation</span><strong>{data.category_counts.automation||0}</strong></article><article><span>Closing</span><strong>{data.category_counts.closing||0}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>FILTERS</span><h2>Audit window</h2></div><div><select value={days} onChange={e=>setDays(Number(e.target.value))}><option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option><option value={365}>365 days</option></select><select value={category} onChange={e=>setCategory(e.target.value)}>{categories.map(c=><option key={c} value={c}>{c||'All categories'}</option>)}</select></div></div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>LEDGER</span><h2>Recent activity</h2></div><strong>{data.items.length}</strong></div><div className={styles.list}>{data.items.length?data.items.map(item=><div key={item.id}><span><b>{item.category.toUpperCase()} · {item.activity_type}</b><small>{item.summary} · {item.user?.email||'system'} · {new Date(item.created_at).toLocaleString()}</small></span><strong>#{item.id}</strong></div>):<p>{data.status==='setup'?'Audit backend is in setup mode.':'No audit events match this filter.'}</p>}</div></section>
    <div className={styles.notice}>{data.retention_note||'Sensitive metadata is redacted before display and export.'}</div>
  </main>;
}

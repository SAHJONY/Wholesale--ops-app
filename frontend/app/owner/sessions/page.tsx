'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/sessions';
const SESSION = 'sahjony_owner_session';

type SessionItem = { id:number; current:boolean; status:string; created_at:string; last_used_at?:string|null; absolute_expires_at:string; idle_expires_at:string; expired:boolean; prefix:string };
type Snapshot = { policy:{absolute_hours:number;idle_hours:number;single_active_session_on_login:boolean};summary:{total:number;active:number;revoked_or_expired:number};sessions:SessionItem[] };
const empty:Snapshot={policy:{absolute_hours:24,idle_hours:2,single_active_session_on_login:true},summary:{total:0,active:0,revoked_or_expired:0},sessions:[]};

export default function SessionSecurityPage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty); const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}const r=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});const text=await r.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}if(r.status===401||r.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}if(!r.ok)throw new Error(body.detail||`Request failed (${r.status})`);return body;},[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load sessions');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function revokeOthers(){setLoading(true);setError('');setNotice('');try{const result=await request('/revoke-others',{method:'POST',body:'{}'});setNotice(`${result.revoked} other session(s) revoked.`);await load();}catch(e){setError(e instanceof Error?e.message:'Unable to revoke sessions');}finally{setLoading(false);}}
  async function revoke(id:number){setLoading(true);setError('');try{await request(`/${id}/revoke`,{method:'POST',body:'{}'});await load();}catch(e){setError(e instanceof Error?e.message:'Unable to revoke session');}finally{setLoading(false);}}
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>SESSION SECURITY</span><h1>Active Device Sessions</h1><p>Review owner sessions, enforce expiration, and revoke access from other devices.</p></div><div className={styles.actions}><button onClick={()=>void revokeOthers()} disabled={loading}>Log out other devices</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/security">Security Center</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Active</span><strong>{data.summary.active}</strong></article><article><span>Total sessions</span><strong>{data.summary.total}</strong></article><article><span>Revoked/expired</span><strong>{data.summary.revoked_or_expired}</strong></article><article><span>Idle timeout</span><strong>{data.policy.idle_hours}h</strong></article><article><span>Maximum age</span><strong>{data.policy.absolute_hours}h</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>DEVICES</span><h2>Session history</h2></div><strong>{data.sessions.length}</strong></div><div className={styles.list}>{data.sessions.length?data.sessions.map(s=><div key={s.id}><span><b>{s.current?'Current device':'Session'} · {s.status.toUpperCase()}</b><small>Created {new Date(s.created_at).toLocaleString()} · last used {s.last_used_at?new Date(s.last_used_at).toLocaleString():'never'}</small><small>Idle expiry {new Date(s.idle_expires_at).toLocaleString()} · absolute expiry {new Date(s.absolute_expires_at).toLocaleString()}</small></span>{!s.current&&s.status==='active'&&!s.expired?<button onClick={()=>void revoke(s.id)} disabled={loading}>Revoke</button>:<strong>{s.expired?'EXPIRED':s.current?'CURRENT':s.status.toUpperCase()}</strong>}</div>):<p>No human login sessions found.</p>}</div></section>
  </main>;
}

'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/public-data';
const SESSION = 'sahjony_owner_session';

type Provider = {
  id:string; name:string; category:string; tier:string; access:string; state:string;
  capabilities:string[]; confidence:string; retention:string; license_required:boolean;
  enabled:boolean; endpoint_configured:boolean; feature_flag:string; endpoint_env:string;
};
type Catalog = { providers:Provider[]; enabled_count:number; licensed_disabled_count:number; safety:Record<string,boolean> };
const empty:Catalog={providers:[],enabled_count:0,licensed_disabled_count:0,safety:{dry_run_default:true,outbound_actions:false,texas_excluded:true,human_approval_required:true}};

export default function PublicDataPage(){
  const [token,setToken]=useState('');
  const [data,setData]=useState<Catalog>(empty);
  const [loading,setLoading]=useState(true);
  const [notice,setNotice]=useState('');

  const load=useCallback(async(override?:string)=>{
    const active=override||token;
    if(!active){location.replace('/owner-access');return;}
    setLoading(true);setNotice('');
    try{
      const response=await fetch(`${API}/catalog`,{cache:'no-store',headers:{Authorization:`Bearer ${active}`}});
      if(response.status===401||response.status===403){location.replace('/owner-access');return;}
      const body=await response.json();
      if(!response.ok) throw new Error(body.detail||`Request failed (${response.status})`);
      setData({...empty,...body,providers:Array.isArray(body.providers)?body.providers:[]});
    }catch(error){setData(empty);setNotice(`Public data center is in setup mode: ${error instanceof Error?error.message:'request failed'}`);}
    finally{setLoading(false);}
  },[token]);

  useEffect(()=>{const stored='cookie-session';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);

  const licensed=data.providers.filter(p=>p.license_required);
  const publicSources=data.providers.filter(p=>!p.license_required);
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>PUBLIC PROPERTY DATA</span><h1>Government & Open Data Network</h1><p>Control official recorder, assessor, court, distress, GIS, FEMA, Census, vacancy, and licensed listing sources with provenance and safety gates.</p></div><div className={styles.actions}><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/integrations">Integration Hub</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}
    <section className={styles.metrics}><article><span>Sources</span><strong>{data.providers.length}</strong></article><article><span>Enabled</span><strong>{data.enabled_count}</strong></article><article><span>Public/free</span><strong>{publicSources.length}</strong></article><article><span>Licensed</span><strong>{licensed.length}</strong></article><article><span>Outbound</span><strong>BLOCKED</strong></article><article><span>Texas</span><strong>EXCLUDED</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>PUBLIC SOURCES</span><h2>Official and open data</h2></div><strong>{publicSources.length}</strong></div><div className={styles.list}>{publicSources.map(p=><div key={p.id}><span><b>{p.name}</b><small>{p.category} · {p.tier} · confidence {p.confidence}</small><small>{p.capabilities.join(', ')}</small><small>Flag: {p.feature_flag} · Endpoint: {p.endpoint_env} · Retention: {p.retention}</small></span><strong>{p.state.toUpperCase()}</strong></div>)}</div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>LICENSED / RESTRICTED</span><h2>Feature-flagged sources</h2></div><strong>{licensed.length}</strong></div><div className={styles.list}>{licensed.map(p=><div key={p.id}><span><b>{p.name}</b><small>{p.access} · license required</small><small>{p.capabilities.join(', ')}</small><small>Disabled until authorized configuration is present.</small></span><strong>{p.state.toUpperCase()}</strong></div>)}</div></section>
  </main>;
}

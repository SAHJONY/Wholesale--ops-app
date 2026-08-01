'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const SESSION = 'sahjony_owner_session';

type Status = {
  provider:string; provider_id:string; public_source:boolean; credential_required:boolean;
  capabilities:string[]; limitations:string[]; safety:Record<string,boolean>;
};
type RunResult = {
  processed_count:number; committed_count:number; skipped_count:number; commit:boolean;
  results:Array<{property_id:number;status:string;address?:string;reason?:string;match?:Record<string,any>}>;
  truth_contract:Record<string,boolean>;
};

export default function LiveDataControlPlane(){
  const [status,setStatus]=useState<Status|null>(null);
  const [result,setResult]=useState<RunResult|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');

  const request=useCallback(async(path:string,options:RequestInit={})=>{
    const token=localStorage.getItem(SESSION)||'';
    if(!token){location.replace('/login?returnTo=/owner/live-data');throw new Error('Owner session required');}
    const response=await fetch(`/api/public-data${path}`,{
      ...options,
      cache:'no-store',
      headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`,...(options.headers||{})},
    });
    const body=await response.json().catch(()=>({}));
    if(response.status===401||response.status===403){localStorage.removeItem(SESSION);location.replace('/login?returnTo=/owner/live-data');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);
    return body;
  },[]);

  const load=useCallback(async()=>{
    setLoading(true);setError('');
    try{setStatus(await request('/live-enrichment/status'));}
    catch(e){setError(e instanceof Error?e.message:'Unable to load live-data status');}
    finally{setLoading(false);}
  },[request]);

  useEffect(()=>{void load();},[load]);

  async function run(commit:boolean){
    if(commit&&!confirm('Enrich up to 25 workspace properties using the public US Census Geocoder and record provenance?'))return;
    setLoading(true);setError('');setNotice('');
    try{
      const data=await request('/live-enrichment/run',{method:'POST',body:JSON.stringify({limit:25,commit})});
      setResult(data);
      setNotice(commit?`${data.committed_count} properties enriched and audited.`:`Preview completed for ${data.processed_count} properties.`);
    }catch(e){setError(e instanceof Error?e.message:'Live enrichment failed');}
    finally{setLoading(false);}
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>REAL PUBLIC DATA</span><h1>Live Data Control Plane</h1><p>Enrich real workspace properties from authoritative public sources while preserving provenance, limitations, and owner control.</p></div>
      <div className={styles.actions}><button onClick={()=>void run(false)} disabled={loading}>Preview enrichment</button><button onClick={()=>void run(true)} disabled={loading}>Run controlled enrichment</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/provider-activation">Provider activation</a><a className={styles.linkButton} href="/owner/properties">Property workspaces</a></div>
    </header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}>
      <article><span>Provider</span><strong>{status?.provider||'Loading'}</strong></article>
      <article><span>Public source</span><strong>{status?.public_source?'YES':'NO'}</strong></article>
      <article><span>Credentials</span><strong>{status?.credential_required?'REQUIRED':'NONE'}</strong></article>
      <article><span>Processed</span><strong>{result?.processed_count||0}</strong></article>
      <article><span>Committed</span><strong>{result?.committed_count||0}</strong></article>
    </section>
    <section className={styles.grid}>
      <article className={styles.card}><span className={styles.eyebrow}>CAPABILITIES</span><h2>What this source verifies</h2><div className={styles.list}>{status?.capabilities.map(item=><div key={item}><span><b>{item.replaceAll('_',' ')}</b><small>Returned with source provenance</small></span><strong>PUBLIC</strong></div>)}</div></article>
      <article className={styles.card}><span className={styles.eyebrow}>TRUTH CONTRACT</span><h2>What it does not verify</h2><div className={styles.list}>{status?.limitations.map(item=><div key={item}><span><b>Limitation</b><small>{item}</small></span><strong>BLOCKED</strong></div>)}</div></article>
    </section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>RESULTS</span><h2>Latest enrichment run</h2></div><strong>{result?.results.length||0}</strong></div><div className={styles.list}>{result?.results.map(row=><div key={row.property_id}><span><b>Property #{row.property_id}</b><small>{row.address||row.reason||'No address returned'}{row.match?.matched_address?` · ${row.match.matched_address}`:''}</small></span><strong>{row.status.toUpperCase()}</strong></div>)}{!result&&<p>No live enrichment run has been performed in this session.</p>}</div></section>
    <div className={styles.notice}>This public provider adds geography and coordinates only. It does not fabricate ownership, seller contacts, liens, valuation, distress, or repair estimates. Paid and licensed providers remain blocked until valid credentials and licenses are configured.</div>
  </main>;
}

'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

type Provider={id:string;name:string;priority:number;public:boolean;configured:boolean;verified:boolean;state:string;missing:string[];capabilities:string[];truth:string[];verification?:{http_status?:number;reason?:string|null;environment?:string}|null};
type Snapshot={version:string;ready_count:number;provider_count:number;eligible_property_count:number;providers:Provider[];orchestration:Record<string,unknown>;safety:Record<string,boolean>};
type ProviderError={provider_id:string;state:string;http_status?:number|null;reason:string};
type ResultRow={property_id:number;status:string;address?:string;reason?:string;canonical?:Record<string,any>;providers_used?:string[];provider_errors?:ProviderError[];confidence?:number;owner_review_required?:boolean;external_actions?:boolean};
type RunResult={version:string;processed_count:number;committed_count:number;skipped_count:number;commit:boolean;results:ResultRow[];truth_contract:Record<string,boolean>};

const stateLabel=(state:string)=>state.replaceAll('_',' ').toUpperCase();

export default function LiveDataControlPlane(){
  const [data,setData]=useState<Snapshot|null>(null);
  const [result,setResult]=useState<RunResult|null>(null);
  const [operation,setOperation]=useState('loading');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [useBatchData,setUseBatchData]=useState(true);
  const loading=operation!=='';

  const request=useCallback(async(path:string,options:RequestInit={})=>{
    try{
      const response=await fetch(`/api/provider-intelligence${path}`,{
        ...options,
        cache:'no-store',
        credentials:'same-origin',
        headers:{'Content-Type':'application/json',...(options.headers||{})},
        signal:options.signal||AbortSignal.timeout(70000),
      });
      const body=await response.json().catch(()=>({}));
      if(response.status===401||response.status===403){
        location.replace('/login?returnTo=/owner/live-data');
        throw new Error('Owner session expired');
      }
      const detail=typeof body.detail==='string'?body.detail:body.detail?.message;
      if(!response.ok)throw new Error(detail||`Request failed (${response.status})`);
      return body;
    }catch(error){
      if(error instanceof DOMException&&error.name==='TimeoutError')throw new Error('Provider check timed out safely. No data was committed; try again.');
      throw error;
    }
  },[]);

  const load=useCallback(async()=>{
    setOperation('refreshing');setError('');
    try{setData(await request('/snapshot'));}
    catch(e){setError(e instanceof Error?e.message:'Unable to load Provider Intelligence');}
    finally{setOperation('');}
  },[request]);

  useEffect(()=>{void load();},[load]);

  async function verify(providerId:string){
    setOperation(`verify:${providerId}`);setError('');setNotice('');
    try{
      const response=await request('/verify',{method:'POST',body:JSON.stringify({provider_id:providerId})});
      const provider=response.provider as Provider;
      setNotice(`${provider.name}: ${stateLabel(provider.state)}${provider.verification?.http_status?` (HTTP ${provider.verification.http_status})`:''}`);
      setData(current=>{
        if(!current)return current;
        const providers=current.providers.map(item=>item.id===provider.id?provider:item);
        const readyCount=providers.filter(item=>item.state==='ready'||item.state==='ready_verified').length;
        return {...current,providers,ready_count:readyCount};
      });
    }catch(e){setError(e instanceof Error?e.message:'Provider verification failed');}
    finally{setOperation('');}
  }

  async function run(commit:boolean){
    if(commit&&!confirm('Commit only governed geography and audit metadata for up to 25 properties? Contact data remains uncommitted and external actions remain blocked.'))return;
    setOperation(commit?'committing':'previewing');setError('');setNotice('');
    try{
      const next=await request('/orchestrate',{
        method:'POST',
        body:JSON.stringify({limit:25,commit,use_batchdata:useBatchData,include_contacts:false}),
      });
      setResult(next);
      setNotice(commit?`${next.committed_count} governed records committed to the audit trail.`:`Preview completed for ${next.processed_count} properties.`);
    }catch(e){setError(e instanceof Error?e.message:'Provider orchestration failed');}
    finally{setOperation('');}
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>PROVIDER INTELLIGENCE V4</span><h1>Canonical Property Intelligence</h1><p>Nationwide provider orchestration with BatchData MCP server-token authentication, Census fallback, field-level provenance, underwriting gates, and owner-controlled commits.</p></div>
      <div className={styles.actions}>
        <button onClick={()=>void run(false)} disabled={loading}>{operation==='previewing'?'Previewing…':'Preview orchestration'}</button>
        <button onClick={()=>void run(true)} disabled={loading}>{operation==='committing'?'Committing…':'Commit governed record'}</button>
        <button onClick={()=>void load()} disabled={loading}>{operation==='refreshing'||operation==='loading'?'Refreshing…':'Refresh'}</button>
        <a className={styles.linkButton} href="/owner/provider-activation">Provider activation</a>
        <a className={styles.linkButton} href="/owner/properties">Property workspaces</a>
      </div>
    </header>

    {notice&&<div className={styles.notice} aria-live="polite">{notice}</div>}
    {error&&<div className={styles.error} aria-live="assertive">{error}</div>}

    <section className={styles.metrics}>
      <article><span>Version</span><strong>{data?.version||'4.0'}</strong></article>
      <article><span>Providers available</span><strong>{data?`${data.ready_count}/${data.provider_count}`:'—'}</strong></article>
      <article><span>BatchData mode</span><strong>{String(data?.orchestration?.batchdata_mode||'—').toUpperCase()}</strong></article>
      <article><span>Processed</span><strong>{result?.processed_count||0}</strong></article>
      <article><span>Committed</span><strong>{result?.committed_count||0}</strong></article>
      <article><span>Skipped</span><strong>{result?.skipped_count||0}</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>RUN CONTROLS</span><h2>Safe provider execution</h2></div></div>
      <label style={{display:'flex',gap:10,alignItems:'center'}}><input type="checkbox" checked={useBatchData} onChange={e=>setUseBatchData(e.target.checked)} /> Use BatchData for this run</label>
      <p>Contact values are redacted in preview and are never committed by this control plane. DNC/TCPA screening and owner approval remain mandatory before communications.</p>
      {data?.eligible_property_count===0&&<div className={styles.notice}>No eligible property workspaces are assigned to this organization. Add or import a complete non-Texas property before running Preview.</div>}
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVIDER MESH</span><h2>Priority, readiness, and credential verification</h2></div><strong>{data?.provider_count||0}</strong></div>
      <div className={styles.list}>{data?.providers.map(p=><div key={p.id}><span><b>{p.name}</b><small>Priority {p.priority} · {p.capabilities.join(', ')}{p.missing.length?` · Missing: ${p.missing.join(', ')}`:''}{p.verification?.environment?` · ${p.verification.environment}`:''}{p.verification?.http_status?` · HTTP ${p.verification.http_status}`:''}{p.verification?.reason?` · ${p.verification.reason}`:''}</small></span><span><strong>{stateLabel(p.state)}</strong>{p.configured&&!p.public&&<button onClick={()=>void verify(p.id)} disabled={loading}>{operation===`verify:${p.id}`?'Checking…':'Verify'}</button>}</span></div>)}{!data&&<p>Loading Provider Intelligence…</p>}</div>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>CANONICAL RESULTS</span><h2>Latest preview or governed commit</h2></div><strong>{result?.results.length||0}</strong></div>
      <div className={styles.list}>{result?.results.map(row=><div key={row.property_id}><span><b>Property #{row.property_id}</b><small>{row.address||row.reason||'No address'}{row.providers_used?.length?` · ${row.providers_used.join(', ')}`:''}{typeof row.confidence==='number'?` · ${Math.round(row.confidence*100)}% confidence`:''}{row.provider_errors?.length?` · ${row.provider_errors.map(e=>`${e.provider_id}: ${stateLabel(e.state)}`).join('; ')}`:''}</small></span><strong>{row.status.toUpperCase()}</strong></div>)}{!result&&<p>No Provider Intelligence v4 run has been performed in this session.</p>}</div>
    </section>

    <div className={styles.notice}>Provider data is evidence, not automatic authority. Ownership, valuation, contacts, ARV, rehab, MAO, offers, calls, texts, emails, and contracts remain blocked until their specific review and approval gates are satisfied.</div>
  </main>;
}

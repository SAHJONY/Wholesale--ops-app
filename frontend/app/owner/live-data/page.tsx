'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

type Provider={id:string;name:string;priority:number;public:boolean;configured:boolean;verified:boolean;state:string;missing:string[];capabilities:string[];truth:string[];verification?:{http_status?:number;reason?:string|null;environment?:string;connected?:boolean}|null};
type Snapshot={version:string;ready_count:number;provider_count:number;providers:Provider[];orchestration:Record<string,unknown>;safety:Record<string,boolean>};
type ProviderError={provider_id:string;state:string;http_status?:number|null;reason:string};
type ResultRow={property_id:number;status:string;address?:string;reason?:string;canonical?:Record<string,any>;providers_used?:string[];provider_errors?:ProviderError[];confidence?:number;owner_review_required?:boolean;external_actions?:boolean};
type RunResult={version:string;processed_count:number;committed_count:number;skipped_count:number;commit:boolean;results:ResultRow[];truth_contract:Record<string,boolean>};

const stateLabel=(state:string)=>state.replaceAll('_',' ').toUpperCase();

export default function LiveDataControlPlane(){
  const [data,setData]=useState<Snapshot|null>(null);
  const [result,setResult]=useState<RunResult|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [useBatchData,setUseBatchData]=useState(true);

  const request=useCallback(async(path:string,options:RequestInit={})=>{
    const response=await fetch(`/api/provider-intelligence${path}`,{
      ...options,
      cache:'no-store',
      credentials:'same-origin',
      headers:{'Content-Type':'application/json',...(options.headers||{})},
    });
    const body=await response.json().catch(()=>({}));
    if(response.status===401||response.status===403){
      location.replace('/login?returnTo=/owner/live-data');
      throw new Error('Owner session expired');
    }
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);
    return body;
  },[]);

  const load=useCallback(async()=>{
    setLoading(true);setError('');
    try{setData(await request('/snapshot'));}
    catch(e){setError(e instanceof Error?e.message:'Unable to load Provider Intelligence');}
    finally{setLoading(false);}
  },[request]);

  useEffect(()=>{
    const oauth=new URLSearchParams(location.search).get('batchdata');
    if(oauth==='connected')setNotice('BatchData MCP OAuth connected. Verify the lookup_property tool before running property queries.');
    if(oauth==='authorization_error'||oauth==='configuration_error')setError('BatchData authorization did not complete. Review the backend configuration and try again.');
    if(oauth)history.replaceState(null,'',location.pathname);
    void load();
  },[load]);

  async function connectBatchData(){
    setLoading(true);setError('');setNotice('');
    try{
      const response=await request('/batchdata/connect',{method:'POST',body:'{}'});
      if(!response.authorization_url)throw new Error('BatchData did not return an authorization URL');
      location.assign(response.authorization_url);
    }catch(e){setError(e instanceof Error?e.message:'Unable to start BatchData authorization');setLoading(false);}
  }

  async function disconnectBatchData(){
    if(!confirm('Disconnect BatchData MCP for this workspace? Property queries will stop until an owner reconnects.'))return;
    setLoading(true);setError('');setNotice('');
    try{await request('/batchdata/disconnect',{method:'POST',body:'{}'});setNotice('BatchData MCP disconnected.');await load();}
    catch(e){setError(e instanceof Error?e.message:'Unable to disconnect BatchData');}
    finally{setLoading(false);}
  }

  async function verify(providerId:string){
    setLoading(true);setError('');setNotice('');
    try{
      const response=await request('/verify',{method:'POST',body:JSON.stringify({provider_id:providerId})});
      const provider=response.provider as Provider;
      setNotice(`${provider.name}: ${stateLabel(provider.state)}${provider.verification?.http_status?` (HTTP ${provider.verification.http_status})`:''}`);
      await load();
    }catch(e){setError(e instanceof Error?e.message:'Provider verification failed');}
    finally{setLoading(false);}
  }

  async function run(commit:boolean){
    if(commit&&!confirm('Commit only governed geography and audit metadata for up to 25 properties? Contact data remains uncommitted and external actions remain blocked.'))return;
    setLoading(true);setError('');setNotice('');
    try{
      const next=await request('/orchestrate',{
        method:'POST',
        body:JSON.stringify({limit:25,commit,use_batchdata:useBatchData,include_contacts:false}),
      });
      setResult(next);
      setNotice(commit?`${next.committed_count} governed records committed to the audit trail.`:`Preview completed for ${next.processed_count} properties.`);
    }catch(e){setError(e instanceof Error?e.message:'Provider orchestration failed');}
    finally{setLoading(false);}
  }

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><span className={styles.eyebrow}>PROVIDER INTELLIGENCE V4</span><h1>Canonical Property Intelligence</h1><p>Nationwide provider orchestration with BatchData MCP OAuth, Census fallback, field-level provenance, underwriting gates, and owner-controlled commits.</p></div>
      <div className={styles.actions}>
        <button onClick={()=>void run(false)} disabled={loading}>Preview orchestration</button>
        <button onClick={()=>void run(true)} disabled={loading}>Commit governed record</button>
        <button onClick={()=>void load()} disabled={loading}>Refresh</button>
        <a className={styles.linkButton} href="/owner/provider-activation">Provider activation</a>
        <a className={styles.linkButton} href="/owner/properties">Property workspaces</a>
      </div>
    </header>

    {notice&&<div className={styles.notice}>{notice}</div>}
    {error&&<div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Version</span><strong>{data?.version||'4.0'}</strong></article>
      <article><span>Providers verified</span><strong>{data?`${data.ready_count}/${data.provider_count}`:'—'}</strong></article>
      <article><span>BatchData mode</span><strong>{String(data?.orchestration?.batchdata_mode||'—').toUpperCase()}</strong></article>
      <article><span>Processed</span><strong>{result?.processed_count||0}</strong></article>
      <article><span>Committed</span><strong>{result?.committed_count||0}</strong></article>
      <article><span>Skipped</span><strong>{result?.skipped_count||0}</strong></article>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>RUN CONTROLS</span><h2>Safe provider execution</h2></div></div>
      <label style={{display:'flex',gap:10,alignItems:'center'}}><input type="checkbox" checked={useBatchData} onChange={e=>setUseBatchData(e.target.checked)} /> Use BatchData for this run</label>
      <p>Contact values are redacted in preview and are never committed by this control plane. DNC/TCPA screening and owner approval remain mandatory before communications.</p>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVIDER MESH</span><h2>Priority, readiness, and credential verification</h2></div><strong>{data?.provider_count||0}</strong></div>
      <div className={styles.list}>{data?.providers.map(p=><div key={p.id}><span><b>{p.name}</b><small>Priority {p.priority} · {p.capabilities.join(', ')}{p.missing.length?` · Missing: ${p.missing.join(', ')}`:''}{p.verification?.environment?` · ${p.verification.environment}`:''}{p.verification?.http_status?` · HTTP ${p.verification.http_status}`:''}{p.verification?.reason?` · ${p.verification.reason}`:''}</small></span><span><strong>{stateLabel(p.state)}</strong>{p.id==='batchdata'&&!p.verification?.connected&&p.configured&&<button onClick={()=>void connectBatchData()} disabled={loading}>Connect OAuth</button>}{p.id==='batchdata'&&p.verification?.connected&&<button onClick={()=>void disconnectBatchData()} disabled={loading}>Disconnect</button>}{p.configured&&!p.public&&(p.id!=='batchdata'||p.verification?.connected)&&<button onClick={()=>void verify(p.id)} disabled={loading}>Verify</button>}</span></div>)}{!data&&<p>Loading provider intelligence.</p>}</div>
    </section>

    <section className={styles.cardWide}>
      <div className={styles.cardHeader}><div><span className={styles.eyebrow}>CANONICAL RESULTS</span><h2>Latest preview or governed commit</h2></div><strong>{result?.results.length||0}</strong></div>
      <div className={styles.list}>{result?.results.map(row=><div key={row.property_id}><span><b>Property #{row.property_id}</b><small>{row.address||row.reason||'No address'}{row.providers_used?.length?` · ${row.providers_used.join(', ')}`:''}{typeof row.confidence==='number'?` · ${Math.round(row.confidence*100)}% confidence`:''}{row.provider_errors?.length?` · ${row.provider_errors.map(e=>`${e.provider_id}: ${stateLabel(e.state)}`).join('; ')}`:''}</small></span><strong>{row.status.toUpperCase()}</strong></div>)}{!result&&<p>No Provider Intelligence v3 run has been performed in this session.</p>}</div>
    </section>

    <div className={styles.notice}>Provider data is evidence, not automatic authority. Ownership, valuation, contacts, ARV, rehab, MAO, offers, calls, texts, emails, and contracts remain blocked until their specific review and approval gates are satisfied.</div>
  </main>;
}

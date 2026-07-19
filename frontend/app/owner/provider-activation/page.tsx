'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/provider-activation';
const SESSION = 'sahjony_owner_session';

type Provider = {
  id:string; name:string; category:string; tier:string; state:string; required_now:boolean; activation_ready:boolean;
  configured_variables:string[]; missing_variables:string[]; optional_configured_variables:string[];
  alternative_configured_variables:string[]; capabilities:string[]; purpose:string; environment:string;
  validation:string; priority:number; url_check?:{valid_url:boolean;host_resolves:boolean;error?:string|null}|null;
};
type Snapshot = {
  generated_at:string; score:number; status:string; required_count:number; ready_count:number; blocker_count:number;
  selected_signature_provider:string; workflows:Record<string,boolean>; providers:Provider[];
};
const empty:Snapshot={generated_at:new Date().toISOString(),score:0,status:'setup',required_count:0,ready_count:0,blocker_count:0,selected_signature_provider:'docuseal',workflows:{},providers:[]};

export default function ProviderActivationPage(){
  const [token,setToken]=useState(''); const [data,setData]=useState<Snapshot>(empty);
  const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const request=useCallback(async(path:string,options:RequestInit={},override?:string)=>{
    const active=override||token;if(!active){location.replace('/owner-access');throw new Error('Owner session required');}
    const response=await fetch(`${API}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(response.status===401||response.status===403){localStorage.removeItem(SESSION);location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);return body;
  },[token]);
  const load=useCallback(async(override?:string)=>{setLoading(true);setError('');try{setData(await request('/snapshot',{},override));}catch(e){setError(e instanceof Error?e.message:'Unable to load provider activation');}finally{setLoading(false);}},[request]);
  useEffect(()=>{const stored=localStorage.getItem(SESSION)||'';if(!stored){location.replace('/owner-access');return;}setToken(stored);void load(stored);},[load]);
  async function verify(id?:string){setLoading(true);setError('');setNotice('');try{await request('/verify',{method:'POST',body:JSON.stringify(id?{provider_id:id}:{})});setNotice(id?`${id} verification completed safely.`:'All provider checks completed safely.');await load();}catch(e){setError(e instanceof Error?e.message:'Unable to verify provider');}finally{setLoading(false);}}
  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>PRODUCTION DATA ACTIVATION</span><h1>Provider Activation Center</h1><p>Activate the licensed property, contact, communications, contract, and document systems that power the wholesale business.</p></div><div className={styles.actions}><button onClick={()=>void verify()} disabled={loading}>Verify all safely</button><button onClick={()=>void load()} disabled={loading}>Refresh</button><a className={styles.linkButton} href="/owner/go-live">Go-Live Center</a><a className={styles.linkButton} href="/owner/integrations">Integration Hub</a><a className={styles.linkButton} href="/owner">Control Plane</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}
    <section className={styles.metrics}><article><span>Activation score</span><strong>{data.score}%</strong></article><article><span>Status</span><strong>{data.status.toUpperCase()}</strong></article><article><span>Ready</span><strong>{data.ready_count}/{data.required_count}</strong></article><article><span>Blockers</span><strong>{data.blocker_count}</strong></article><article><span>Signature</span><strong>{data.selected_signature_provider.toUpperCase()}</strong></article></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>WORKFLOWS</span><h2>Business readiness</h2></div></div><div className={styles.list}>{Object.entries(data.workflows).map(([name,ready])=><div key={name}><span><b>{name.replaceAll('_',' ')}</b><small>{ready?'Operationally ready':'Blocked by provider setup'}</small></span><strong>{ready?'READY':'BLOCKED'}</strong></div>)}</div></section>
    <section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>PROVIDERS</span><h2>Activation queue</h2></div><strong>{data.providers.length}</strong></div><div className={styles.list}>{data.providers.length?data.providers.map(provider=><div key={provider.id}><span><b>{provider.name}</b><small>{provider.purpose} · {provider.validation}{provider.missing_variables.length?` · Missing: ${provider.missing_variables.join(', ')}`:''}{provider.url_check?` · URL ${provider.url_check.valid_url?'valid':'invalid'} / host ${provider.url_check.host_resolves?'resolves':'unresolved'}`:''}</small></span><span><strong>{provider.activation_ready?'READY':provider.required_now?'BLOCKED':'OPTIONAL'}</strong><button onClick={()=>void verify(provider.id)} disabled={loading}>Verify</button></span></div>):<p>Provider activation backend is in setup mode.</p>}</div></section>
    <div className={styles.notice}>Verification is non-destructive: no messages, calls, signature submissions, payments, or storage writes are performed. Credentials are never returned to the browser.</div>
  </main>;
}

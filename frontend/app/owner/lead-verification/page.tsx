'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API='/api/lead-verification';
const SIGN_IN='/login?returnTo=/owner/lead-verification';
type LeadRow={lead_id:number;seller_name:string;property_id:number;address:string;city:string;state:string;verified:boolean;map_url:string|null;reason:string|null};

export default function LeadVerificationPage(){
 const[enforcement,setEnforcement]=useState<boolean|null>(null);const[summary,setSummary]=useState<Record<string,number>|null>(null);const[verified,setVerified]=useState<LeadRow[]>([]);const[quarantined,setQuarantined]=useState<LeadRow[]>([]);const[rule,setRule]=useState('');const[remediation,setRemediation]=useState('');const[loading,setLoading]=useState(false);const[error,setError]=useState('');
 const request=useCallback(async(path:string)=>{const response=await fetch(`${API}${path}`,{cache:'no-store',credentials:'same-origin'});const text=await response.text();let body:any={};if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}if(response.status===401||response.status===403){const sr=await fetch('/api/owner-access/session',{cache:'no-store',credentials:'same-origin'});const session=await sr.json().catch(()=>({}));if(!sr.ok||!session.authenticated){window.location.replace(SIGN_IN);throw new Error('Owner session required');}throw new Error('Your owner session is valid, but Lead Verification rejected this request. Stay on this page and review System Health if it persists.');}if(!response.ok)throw new Error(body.detail||`Request failed (${response.status})`);return body},[]);
 const load=useCallback(async()=>{setLoading(true);setError('');try{const body=await request('/status');setEnforcement(body.enforcement_enabled);setSummary(body.summary||null);setVerified(body.verified||[]);setQuarantined(body.quarantined||[]);setRule(body.rule||'');setRemediation(body.remediation||'')}catch(e){setError(e instanceof Error?e.message:'Unable to load verification status')}finally{setLoading(false)}},[request]);
 useEffect(()=>{void load()},[load]);
 const coverage=summary?.coverage_percent??0;
 return <main className={styles.page}>
  <header className={styles.header}><div><span className={styles.eyebrow}>DATA INTEGRITY</span><h1>Lead Verification</h1><p>{rule||'A lead is actionable only when its property verifies to a locatable real place.'}</p></div><div className={styles.actions}><button className={styles.runButton} onClick={()=>void load()} disabled={loading}>{loading?'Refreshing…':'Refresh'}</button><Link className={styles.linkButton} href="/owner/market-intelligence">Market Intelligence</Link><Link className={styles.linkButton} href="/owner/owner-resolution">Owner Resolution</Link><Link className={styles.linkButton} href="/owner">Command</Link></div></header>
  {error&&<div className={styles.error}>{error}</div>}
  {enforcement===false&&<div className={styles.error}>Verification enforcement is disabled. Unverified leads can currently be actioned. Unset REQUIRE_VERIFIED_LEADS to restore the gate.</div>}
  {summary&&<section className={styles.metrics}><article><span>Total leads</span><strong>{summary.total_leads}</strong></article><article><span>Verified &amp; locatable</span><strong>{summary.verified_and_locatable}</strong></article><article><span>Quarantined</span><strong>{summary.quarantined}</strong></article><article><span>Coverage</span><strong>{coverage}%</strong></article></section>}
  {summary&&summary.total_leads>0&&coverage===0&&<div className={styles.cycleSummary}>No lead has verified yet. {remediation} Verification requires the Census geocoder to be reachable from the backend.</div>}
  <section className={styles.cardWide}><div className={styles.cardHeader}><h2>Verified &amp; locatable</h2><strong>{verified.length}</strong></div><div className={styles.list}>{verified.length?verified.map(row=><div key={row.lead_id}><span><b>{row.seller_name} · lead #{row.lead_id}</b><small>{row.address}, {row.city} {row.state}</small></span><span className={styles.decisionButtons}><span className={styles.healthy}>verified</span>{row.map_url&&<a className={styles.linkButton} href={row.map_url} target="_blank" rel="noreferrer">Open in Maps</a>}</span></div>):<p>No verified leads yet.</p>}</div></section>
  <section className={styles.cardWide}><div className={styles.cardHeader}><h2>Quarantined</h2><small>Blocked from outreach until they verify. Held rather than deleted so no operator entry is lost.</small></div><div className={styles.list}>{quarantined.length?quarantined.map(row=><div key={row.lead_id}><span><b>{row.seller_name} · lead #{row.lead_id}</b><small>{row.address}, {row.city} {row.state}</small><small>{row.reason||'Not verified against public records'}</small></span><span className={styles.risk}>quarantined</span></div>):<p>Nothing quarantined.</p>}</div></section>
 </main>;
}

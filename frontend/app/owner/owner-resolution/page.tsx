'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import styles from '../owner.module.css';

type Candidate = { lead_id:number; property_id?:number; address?:string; city?:string; state?:string; zip_code?:string; source:string; asking_price?:number; created_at:string };
type Evidence = { activity_id:number; source_name:string; source_url:string; retrieved_at?:string; candidate_phone?:string|null; candidate_email?:string|null; identity_match_confidence:number; evidence_notes?:string|null };
type Resolution = { evidence_count:number; evidence:Evidence[]; cross_verified_phones:string[]; cross_verified_emails:string[]; max_identity_match_confidence:number; status:'unverified'|'likely'|'cross_verified'|'contact_ready'; contact_ready:boolean; outreach_allowed:boolean; note:string };
type Packet = { lead_id:number; property_id:number; property_address:string; city:string; state:string; zip_code:string; owner_of_record_name?:string|null; owner_mailing_address?:string|null; identity_status:string; lookup_fields:Record<string,string|null>; manual_assisted_resolvers:Record<string,{label:string;url:string;mode:string}>; next_step:string; outreach_allowed:boolean; resolution:Resolution };

const ACQ='/api/acquisition-intake';
const RES='/api/owner-resolution';

export default function OwnerResolutionDesk(){
  const [token,setToken]=useState('');
  const [candidates,setCandidates]=useState<Candidate[]>([]);
  const [selectedLead,setSelectedLead]=useState<number|''>('');
  const [packet,setPacket]=useState<Packet|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [sourceName,setSourceName]=useState('truepeoplesearch');
  const [sourceUrl,setSourceUrl]=useState('https://www.truepeoplesearch.com/');
  const [phone,setPhone]=useState('');
  const [email,setEmail]=useState('');
  const [confidence,setConfidence]=useState('85');
  const [mailingAddress,setMailingAddress]=useState('');
  const [notes,setNotes]=useState('Exact owner name and address matched the property/owner record.');

  const request=useCallback(async(base:string,path:string,options:RequestInit={},override?:string)=>{
    const active=override||token||'cookie-session';
    const response=await fetch(`${base}${path}`,{...options,cache:'no-store',headers:{'Content-Type':'application/json',Authorization:`Bearer ${active}`,...(options.headers||{})}});
    const text=await response.text(); let body:any={};
    if(text){try{body=JSON.parse(text)}catch{body={detail:text}}}
    if(response.status===401||response.status===403){location.replace('/owner-access');throw new Error('Owner session expired');}
    if(!response.ok){const detail=typeof body.detail==='string'?body.detail:body.detail?.message||body.message;throw new Error(detail||`Request failed (${response.status})`);}
    return body;
  },[token]);

  const loadPacket=useCallback(async(leadId:number,override?:string)=>{
    setError('');
    const body=await request(RES,`/leads/${leadId}/packet`,{},override);
    setPacket(body);
    setSelectedLead(leadId);
    if(body.owner_mailing_address) setMailingAddress(body.owner_mailing_address);
  },[request]);

  const load=useCallback(async(override?:string)=>{
    setLoading(true); setError('');
    try{
      const snapshot=await request(ACQ,'/snapshot',{},override);
      const items=(snapshot.candidates||[]) as Candidate[];
      setCandidates(items);
      const queryLead=Number(new URLSearchParams(location.search).get('lead')||0);
      const initial=(queryLead&&items.some(x=>x.lead_id===queryLead)?queryLead:items[0]?.lead_id)||0;
      if(initial) await loadPacket(initial,override);
    }catch(e){setError(e instanceof Error?e.message:'Unable to load owner resolution desk');}
    finally{setLoading(false);}
  },[loadPacket,request]);

  useEffect(()=>{const stored='cookie-session';setToken(stored);void load(stored);},[load]);

  async function queueCandidates(){setLoading(true);setError('');setNotice('');try{const r=await request(RES,'/queue-property-candidates',{method:'POST',body:JSON.stringify({limit:500})});setNotice(`${r.queued} owner-resolution tasks queued; ${r.skipped_existing} already active. Outreach remains blocked.`);}catch(e){setError(e instanceof Error?e.message:'Unable to queue candidates');}finally{setLoading(false);}}

  async function recordEvidence(e:FormEvent){e.preventDefault();if(!selectedLead)return;setLoading(true);setError('');setNotice('');try{const r=await request(RES,`/leads/${selectedLead}/evidence`,{method:'POST',body:JSON.stringify({source_name:sourceName,source_url:sourceUrl,candidate_phone:phone,candidate_email:email,identity_match_confidence:Number(confidence),owner_of_record_name:packet?.owner_of_record_name||'',owner_mailing_address:mailingAddress,evidence_notes:notes})});setPacket(prev=>prev?{...prev,resolution:r.resolution}:prev);setNotice(`Evidence recorded. Resolution status: ${String(r.resolution.status).replace('_',' ')}.`);setPhone('');setEmail('');}catch(e){setError(e instanceof Error?e.message:'Unable to record evidence');}finally{setLoading(false);}}

  async function applyContact(){if(!selectedLead)return;setLoading(true);setError('');setNotice('');try{const r=await request(RES,`/leads/${selectedLead}/apply-contact-ready`,{method:'POST',body:JSON.stringify({})});setNotice(`Cross-verified contact applied: ${Object.keys(r.applied||{}).join(', ')||'no empty lead fields needed replacement'}. Outreach is still blocked pending compliance.`);await loadPacket(Number(selectedLead));}catch(e){setError(e instanceof Error?e.message:'Unable to apply contact');}finally{setLoading(false);}}

  function selectSource(value:string){setSourceName(value);setSourceUrl(value==='truepeoplesearch'?'https://www.truepeoplesearch.com/':'https://www.cyberbackgroundchecks.com/');}
  const status=packet?.resolution?.status||'unverified';
  const statusLabel=status.replaceAll('_',' ').toUpperCase();
  const evidenceBySource=useMemo(()=>new Set(packet?.resolution?.evidence.map(x=>x.source_name)||[]),[packet]);

  return <main className={styles.page}>
    <header className={styles.header}><div><span className={styles.eyebrow}>OWNER INTELLIGENCE</span><h1>Owner Resolution Desk</h1><p>Turn distressed property candidates into source-backed owner/contact intelligence without bypassing site controls or treating public data as permission to market.</p></div><div className={styles.actions}><button onClick={()=>void load()} disabled={loading}>Refresh</button><button onClick={()=>void queueCandidates()} disabled={loading||!candidates.length}>Queue all</button><a className={styles.linkButton} href="/owner/acquisition">Prospects</a><a className={styles.linkButton} href="/owner/lead-verification">Verification</a></div></header>
    {notice&&<div className={styles.notice}>{notice}</div>}{error&&<div className={styles.error}>{error}</div>}

    <section className={styles.metrics}>
      <article><span>Property candidates</span><strong>{candidates.length}</strong></article>
      <article><span>Resolution status</span><strong>{statusLabel}</strong></article>
      <article><span>Evidence</span><strong>{packet?.resolution?.evidence_count||0}</strong></article>
      <article><span>Confidence</span><strong>{Math.round(packet?.resolution?.max_identity_match_confidence||0)}%</strong></article>
      <article><span>Independent sources</span><strong>{evidenceBySource.size}/2</strong></article>
      <article><span>Outreach</span><strong>BLOCKED</strong></article>
    </section>

    <section className={styles.grid}>
      <article className={styles.card}><span className={styles.eyebrow}>SELECT PROPERTY</span><h2>Resolution queue</h2><label>Property candidate<select value={selectedLead} onChange={e=>{const id=Number(e.target.value);setSelectedLead(id);void loadPacket(id);}} disabled={!candidates.length}>{candidates.map(item=><option key={item.lead_id} value={item.lead_id}>#{item.lead_id} · {item.address}, {item.city} {item.state}</option>)}</select></label><div className={styles.list}>{candidates.slice(0,20).map(item=><div key={item.lead_id}><span><b>{item.address}, {item.city} {item.state} {item.zip_code}</b><small>Lead #{item.lead_id} · {item.source}</small></span><button type="button" onClick={()=>void loadPacket(item.lead_id)}>Open</button></div>)}</div></article>

      <article className={styles.card}><span className={styles.eyebrow}>OWNER PACKET</span><h2>{packet?.property_address||'Select a candidate'}</h2>{packet?<div className={styles.list}><div><span><b>Owner of record</b><small>{packet.owner_of_record_name||'Owner record required'}</small></span><strong>{packet.identity_status.replaceAll('_',' ')}</strong></div><div><span><b>Property</b><small>{packet.property_address}, {packet.city}, {packet.state} {packet.zip_code}</small></span></div><div><span><b>Next step</b><small>{packet.next_step}</small></span></div><div><span><b>Identity evidence</b><small>{packet.resolution.note}</small></span><strong>{statusLabel}</strong></div></div>:<p>No packet selected.</p>}</article>
    </section>

    {packet&&<section className={styles.cardWide}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>MANUAL-ASSISTED RESOLUTION</span><h2>Research owner candidates</h2><p>Open a public resolver manually, use the prepared owner/property fields, then record only the evidence you actually observed. No CAPTCHA, Cloudflare, login or rate-limit bypass is used by SAHJONY.</p></div><strong>2-SOURCE GATE</strong></div><div className={styles.actions}>{Object.entries(packet.manual_assisted_resolvers).map(([key,item])=><a key={key} className={styles.linkButton} href={item.url} target="_blank" rel="noreferrer">Open {item.label}</a>)}</div><div className={styles.list}><div><span><b>Lookup name</b><small>{packet.lookup_fields.name||'Verify owner first'}</small></span></div><div><span><b>Property address</b><small>{packet.lookup_fields.property_address}, {packet.lookup_fields.city}, {packet.lookup_fields.state} {packet.lookup_fields.zip_code}</small></span></div></div></section>}

    {packet&&<section className={styles.grid}><article className={styles.card}><span className={styles.eyebrow}>RECORD EVIDENCE</span><h2>Add observed contact candidate</h2><form className={styles.activationForm} onSubmit={recordEvidence}><label>Source<select value={sourceName} onChange={e=>selectSource(e.target.value)}><option value="truepeoplesearch">TruePeopleSearch</option><option value="cyberbackgroundchecks">CyberBackgroundChecks</option></select></label><label>Source URL<input type="url" value={sourceUrl} onChange={e=>setSourceUrl(e.target.value)} required /></label><label>Owner mailing address<input value={mailingAddress} onChange={e=>setMailingAddress(e.target.value)} placeholder="Observed mailing address, if available" /></label><label>Candidate phone<input inputMode="tel" value={phone} onChange={e=>setPhone(e.target.value)} placeholder="10-digit US phone" /></label><label>Candidate email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="owner@example.com" /></label><label>Identity confidence<input type="number" min="0" max="100" value={confidence} onChange={e=>setConfidence(e.target.value)} required /></label><label>Evidence notes<textarea rows={4} value={notes} onChange={e=>setNotes(e.target.value)} required /></label><button disabled={loading||(!phone.trim()&&!email.trim())}>{loading?'Saving…':'Record source evidence'}</button><small>One source can establish a candidate, not Contact Ready. The same phone/email must be corroborated independently before application.</small></form></article>

      <article className={styles.card}><div className={styles.cardHeader}><div><span className={styles.eyebrow}>EVIDENCE TRAIL</span><h2>Identity resolution</h2></div><strong>{packet.resolution.evidence_count}</strong></div><div className={styles.list}>{packet.resolution.evidence.length?packet.resolution.evidence.map(ev=><div key={ev.activity_id}><span><b>{ev.source_name}</b><small>{ev.candidate_phone||ev.candidate_email||'No contact'} · confidence {Math.round(ev.identity_match_confidence)}%</small><small>{ev.evidence_notes}</small></span><a className={styles.linkButton} href={ev.source_url} target="_blank" rel="noreferrer">Source</a></div>):<p>No owner-resolution evidence recorded yet.</p>}</div>{packet.resolution.cross_verified_phones.length>0&&<p>Cross-verified phone: <strong>{packet.resolution.cross_verified_phones[0]}</strong></p>}{packet.resolution.cross_verified_emails.length>0&&<p>Cross-verified email: <strong>{packet.resolution.cross_verified_emails[0]}</strong></p>}<button type="button" onClick={()=>void applyContact()} disabled={loading||!packet.resolution.contact_ready}>{packet.resolution.contact_ready?'Apply Contact Ready':'Needs two matching sources + 80% confidence'}</button><small>Applying identity evidence never starts a call or SMS. DNC/TCPA/state policy remains a separate downstream gate.</small></article></section>}
  </main>;
}

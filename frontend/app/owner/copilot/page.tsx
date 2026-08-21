'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import styles from './copilot.module.css';

type Status = {
  configured: boolean;
  model: string;
  responses_api: boolean;
  tools: {
    web_search: boolean;
    file_search: boolean;
    workspace_functions: string[];
    computer_use: boolean;
    realtime_voice: boolean;
  };
  note: string;
};

type ImportResult={created_count:number;duplicate_count:number;rejected_count:number;status:string};
type Message = { role: 'user' | 'assistant'; text: string; responseId?:string; tools?: string[]; sources?: string[]; importResult?:ImportResult; importing?:boolean; feedback?:string };

const suggestions = [
  'Find the strongest single-family opportunities already in my Deal Factory and explain what is missing before I can call them real $10K+ deals.',
  'Research nationwide for current distressed single-family opportunities with individual owners, then tell me which public records I must verify before importing them.',
  'Analyze my best current property, verify the owner/deed evidence in the workspace, compare it to my buyer network, and give me the next five actions.',
  'Show me which deals have enough evidence to pursue today and which should be rejected or renegotiated.',
];

export default function CopilotPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`/api/copilot${path}`, {
      cache: 'no-store',
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace('/login?returnTo=/owner/copilot');
      throw new Error('Owner session required');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, []);

  useEffect(() => {
    void request('/status').then(setStatus).catch(err => setError(err instanceof Error ? err.message : 'Unable to load Copilot status'));
  }, [request]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setMessages(current => [...current, { role: 'user', text: message }]);
    setInput(''); setBusy(true); setError('');
    try {
      const data = await request('/chat', { method: 'POST', body: JSON.stringify({ message }) });
      setMessages(current => [...current, {
        role: 'assistant',
        text: data.answer || 'The Copilot returned no text.',
        responseId:data.response_id,
        tools: (data.tools_used || []).map((item: { name: string }) => item.name),
        sources: [
          ...(data.web_sources || []).map((item: { url: string }) => item.url),
          ...(data.file_sources || []).map((item: { filename?: string; file_id?: string }) => item.filename || item.file_id).filter(Boolean),
        ],
        importing: true,
      }]);
      try {
        const imported=await request('/import',{method:'POST',body:JSON.stringify({response_id:data.response_id,answer:data.answer,web_sources:data.web_sources||[]})});
        setMessages(current=>current.map(item=>item.importing?{...item,importing:false,importResult:imported}:item));
      } catch(importError) {
        setMessages(current=>current.map(item=>item.importing?{...item,importing:false}:item));
        setError(importError instanceof Error?`Research completed, but lead staging failed: ${importError.message}`:'Research completed, but lead staging failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Copilot request failed');
    } finally { setBusy(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void send(input); }

  async function rate(responseId:string|undefined,rating:'useful'|'not_useful'){
    if(!responseId)return;
    try{const response=await fetch('/api/backend/openai-copilot/feedback',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({response_id:responseId,rating})});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||`Feedback failed (${response.status})`);setMessages(current=>current.map(item=>item.responseId===responseId?{...item,feedback:rating}:item))}
    catch(err){setError(err instanceof Error?err.message:'Unable to save Copilot feedback')}
  }

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div><span>SAHJONY · OPENAI WHOLESALE COPILOT</span><h1>Your wholesale operating system now has an agentic research and deal-analysis surface.</h1><p>Ask it to research the web, inspect source-grounded workspace facts, analyze owner/deed evidence, rank deals, and match buyers. Consequential actions remain human-controlled.</p></div>
      <div className={styles.statusCard}>
        <div><i className={status?.configured ? styles.live : styles.offline}/><b>{status?.configured ? 'OpenAI connected' : 'OpenAI key required'}</b></div>
        <small>{status?.model || 'Model not loaded'}</small>
        <small>Responses API {status?.responses_api ? 'enabled' : 'unavailable'}</small>
      </div>
    </header>

    <section className={styles.capabilities}>
      <article><span>WEB</span><b>{status?.tools.web_search ? 'Web Search' : 'Unavailable'}</b><small>Current nationwide research</small></article>
      <article><span>FILES</span><b>{status?.tools.file_search ? 'Knowledge Base Live' : 'Vector store not configured'}</b><small>Authorized books, SOPs and deal files</small></article>
      <article><span>TOOLS</span><b>{status?.tools.workspace_functions?.length || 0} workspace functions</b><small>Deals, properties, buyers and skills</small></article>
      <article><span>SAFETY</span><b>Supervised autonomy</b><small>No silent offers, contracts or payments</small></article>
    </section>

    {!status?.configured && <section className={styles.setup}><b>Activation required</b><p>Set <code>OPENAI_API_KEY</code> in this Vercel project. To enable source-grounded file search, also set <code>OPENAI_VECTOR_STORE_ID</code>.</p></section>}
    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.workspace}>
      <aside className={styles.prompts}>
        <span>START HERE</span><h2>Wholesale operating commands</h2>
        {suggestions.map(text => <button key={text} type="button" onClick={() => void send(text)} disabled={busy || !status?.configured}>{text}</button>)}
        <div className={styles.boundary}><b>AI boundary</b><small>Research · verify · analyze · draft · recommend</small><small>Human approval: offers · contracts · campaigns · payments</small></div>
      </aside>

      <div className={styles.chat}>
        <div className={styles.thread}>
          {messages.length === 0 ? <div className={styles.empty}><b>Ask SAHJONY about a deal or market.</b><span>Example: “Find my best $10K+ single-family opportunity and tell me what owner/deed facts still need verification.”</span></div> : messages.map((message, index) => <article key={index} className={message.role === 'user' ? styles.user : styles.assistant}>
            <span>{message.role === 'user' ? 'YOU' : 'SAHJONY COPILOT'}</span><p>{message.text}</p>
            {!!message.tools?.length && <small>Tools: {Array.from(new Set(message.tools)).join(' · ')}</small>}
            {message.importing&&<div style={{marginTop:12,padding:12,border:'1px solid rgba(212,175,55,.32)',borderRadius:11,color:'#f4df9a'}}>Saving sourced candidates and checking duplicates…</div>}
            {message.importResult&&<div style={{marginTop:12,padding:12,border:'1px solid rgba(212,175,55,.32)',borderRadius:11,color:'#f4df9a'}}><b>{message.importResult.created_count} new lead{message.importResult.created_count===1?'':'s'} saved</b><small style={{display:'block',marginTop:4}}>{message.importResult.duplicate_count} duplicate · {message.importResult.rejected_count} insufficient evidence · Verification required before promotion</small></div>}
            {message.role==='assistant'&&message.responseId&&<div style={{display:'flex',gap:8,marginTop:10}}><button type="button" onClick={()=>void rate(message.responseId,'useful')} disabled={!!message.feedback}>{message.feedback==='useful'?'✓ Useful':'Useful'}</button><button type="button" onClick={()=>void rate(message.responseId,'not_useful')} disabled={!!message.feedback}>{message.feedback==='not_useful'?'✓ Needs improvement':'Needs improvement'}</button></div>}
            {!!message.sources?.length && <details><summary>{message.sources.length} source{message.sources.length === 1 ? '' : 's'}</summary>{message.sources.map(source => <span key={source}>{source}</span>)}</details>}
          </article>)}
          {busy && <div className={styles.thinking}>Researching and analyzing with bounded tools…</div>}
        </div>
        <form onSubmit={submit} className={styles.composer}>
          <textarea value={input} onChange={event => setInput(event.target.value)} placeholder="Ask about a property, owner/deed verification, nationwide leads, ARV, buyers, or next actions…" rows={4}/>
          <button type="submit" disabled={busy || !input.trim() || !status?.configured}>{busy ? 'Working…' : 'Run Copilot'}</button>
        </form>
      </div>
    </section>
  </main>;
}

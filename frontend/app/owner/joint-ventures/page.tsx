'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import styles from './joint-ventures.module.css';

type Metrics={
  submissions:number;
  closed_jvs:number;
  conversion_rate_percent:number;
  projected_gross_assignment_revenue:number;
  jv_gross_assignment_revenue:number;
  projected_sahjony_revenue:number;
  realized_sahjony_revenue:number;
  average_sahjony_split_percent:number|null;
  average_days_to_buyer:number|null;
  deals_with_buyer:number;
};

type JointVenture={
  id:number;
  name?:string;
  company?:string;
  email?:string;
  phone?:string;
  property_address?:string;
  city?:string;
  state?:string;
  zip_code?:string;
  contract_status?:string;
  contract_price?:number|null;
  buyer_price?:number|null;
  arv?:number|null;
  repairs?:number|null;
  sahjony_split_percent?:number|null;
  stage:string;
  buyer_status?:string;
  gross_assignment_fee?:number|null;
  sahjony_revenue?:number|null;
  partner_revenue?:number|null;
  days_to_buyer?:number|null;
  created_at?:string;
};

type EngineResponse={metrics:Metrics;joint_ventures:JointVenture[]};
type CalcResult={gross_assignment_fee:number;sahjony_revenue:number|null;partner_revenue:number|null;assignment_margin_on_buyer_price_percent:number|null};

const money=(value:number|null|undefined)=>value==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
const pct=(value:number|null|undefined)=>value==null?'—':`${value.toFixed(1)}%`;

export default function JointVenturesPage(){
  const [data,setData]=useState<EngineResponse|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [calc,setCalc]=useState<CalcResult|null>(null);
  const [calcError,setCalcError]=useState('');

  async function load(){
    setLoading(true);setError('');
    try{
      const response=await fetch('/api/backend/joint-ventures',{cache:'no-store',headers:{Authorization:'Bearer cookie-session'}});
      if(response.status===401||response.status===403){window.location.replace('/login?returnTo=/owner/joint-ventures');return;}
      if(!response.ok)throw new Error(`Request failed (${response.status})`);
      setData(await response.json() as EngineResponse);
    }catch(err){setError(err instanceof Error?err.message:'Unable to load JV engine');}
    finally{setLoading(false);}
  }

  useEffect(()=>{void load();},[]);

  async function calculate(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setCalc(null);setCalcError('');
    const values=Object.fromEntries(new FormData(event.currentTarget).entries());
    try{
      const response=await fetch('/api/backend/joint-ventures/assignment-fee',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer cookie-session'},body:JSON.stringify(values)});
      const body=await response.json();
      if(!response.ok)throw new Error(body.detail||'Unable to calculate assignment fee');
      setCalc(body as CalcResult);
    }catch(err){setCalcError(err instanceof Error?err.message:'Unable to calculate assignment fee');}
  }

  const metrics=data?.metrics;
  const recent=useMemo(()=>data?.joint_ventures?.slice(0,30)||[],[data]);
  const needsBuyer=useMemo(()=>recent.filter(item=>item.buyer_status==='need_buyer').length,[recent]);
  const underContract=useMemo(()=>recent.filter(item=>item.contract_status==='under_contract').length,[recent]);

  return <main className={styles.page}>
    <header className={styles.hero}><div><span>SAHJONY WHOLESALE OS · JV REVENUE ENGINE</span><h1>Assignment fees, JV revenue, split economics, conversion, and buyer velocity.</h1><p>One source of truth for wholesaler JV economics. Projected revenue is separated from realized closed revenue, and days-to-buyer begins only when a buyer is actually documented.</p></div><div className={styles.actions}><a href="/joint-venture" target="_blank" rel="noreferrer">Open public JV page</a><a href="/owner/deal-intelligence">Underwrite deal</a><a href="/owner/disposition">Buyer matching</a></div></header>

    {error&&<div className={styles.error}>{error}</div>}

    <section className={styles.kpis}>
      <article><span>JV submissions</span><strong>{loading?'—':metrics?.submissions??0}</strong><small>{underContract} reported under contract</small></article>
      <article><span>Gross JV revenue</span><strong>{loading?'—':money(metrics?.jv_gross_assignment_revenue)}</strong><small>Closed assignment fees before split</small></article>
      <article><span>SAHJONY realized</span><strong>{loading?'—':money(metrics?.realized_sahjony_revenue)}</strong><small>Closed revenue after JV split</small></article>
      <article><span>Projected gross fees</span><strong>{loading?'—':money(metrics?.projected_gross_assignment_revenue)}</strong><small>Active deals with buyer + contract price</small></article>
      <article><span>Average split</span><strong>{loading?'—':pct(metrics?.average_sahjony_split_percent)}</strong><small>SAHJONY share on documented JV splits</small></article>
      <article><span>Conversion rate</span><strong>{loading?'—':pct(metrics?.conversion_rate_percent)}</strong><small>Closed JV deals ÷ submissions</small></article>
      <article><span>Days to buyer</span><strong>{loading?'—':metrics?.average_days_to_buyer==null?'—':`${metrics.average_days_to_buyer.toFixed(1)}d`}</strong><small>{metrics?.deals_with_buyer??0} deals with buyer timestamps</small></article>
      <article><span>Need buyers</span><strong>{loading?'—':needsBuyer}</strong><small>Immediate disposition queue</small></article>
    </section>

    <section className={styles.calculator}>
      <div><span>ASSIGNMENT FEE ENGINE</span><h2>Calculate the economics before a JV is approved.</h2><p>Gross assignment fee = buyer/disposition price − seller/contract price. The approved SAHJONY split then determines company revenue; the remainder is the JV partner share.</p></div>
      <form onSubmit={calculate} className={styles.calcGrid}>
        <label><span>Contract price</span><input name="contract_price" inputMode="decimal" placeholder="75000" required/></label>
        <label><span>Buyer price</span><input name="buyer_price" inputMode="decimal" placeholder="105000" required/></label>
        <label><span>SAHJONY split %</span><input name="sahjony_split_percent" inputMode="decimal" placeholder="50"/></label>
        <button type="submit">Calculate fee</button>
      </form>
      {calcError&&<div className={styles.error}>{calcError}</div>}
      {calc&&<div className={styles.calcResults}><article><span>Gross assignment fee</span><strong>{money(calc.gross_assignment_fee)}</strong></article><article><span>SAHJONY revenue</span><strong>{money(calc.sahjony_revenue)}</strong></article><article><span>JV partner revenue</span><strong>{money(calc.partner_revenue)}</strong></article><article><span>Assignment margin</span><strong>{pct(calc.assignment_margin_on_buyer_price_percent)}</strong></article></div>}
    </section>

    <section className={styles.workflow}><div><span>JV CONTROL GATES</span><h2>Revenue is counted only after the deal survives execution controls.</h2></div><div className={styles.steps}><article><b>01</b><h3>Authority</h3><p>Confirm seller control or an assignable contract and all marketing restrictions.</p></article><article><b>02</b><h3>Economics</h3><p>Verify ARV, repairs, contract basis, buyer price, and assignment spread.</p></article><article><b>03</b><h3>JV terms</h3><p>Record the approved SAHJONY percentage; proposed splits are not payment obligations.</p></article><article><b>04</b><h3>Buyer found</h3><p>Timestamp first documented buyer identification to measure disposition velocity.</p></article><article><b>05</b><h3>Closed</h3><p>Only closed deals enter realized gross JV and SAHJONY revenue.</p></article></div></section>

    <section className={styles.panel}><div className={styles.sectionHead}><div><span>JV PIPELINE</span><h2>Deal-level economics</h2></div><button className={styles.refresh} type="button" onClick={()=>void load()}>Refresh</button></div>{loading?<div className={styles.empty}>Loading JV revenue engine…</div>:recent.length?<div className={styles.tableWrap}><table><thead><tr><th>JV / Partner</th><th>Market</th><th>Stage</th><th>Contract</th><th>Buyer</th><th>Gross fee</th><th>SAHJONY</th><th>Split</th><th>Days to buyer</th></tr></thead><tbody>{recent.map(item=><tr key={item.id}><td><b>JV #{item.id}</b><small>{item.company||item.name||'—'}</small></td><td>{[item.city,item.state,item.zip_code].filter(Boolean).join(', ')||'—'}</td><td><span className={styles.stage}>{item.stage.replaceAll('_',' ')}</span></td><td>{money(item.contract_price)}</td><td>{money(item.buyer_price)}</td><td><b>{money(item.gross_assignment_fee)}</b></td><td>{money(item.sahjony_revenue)}</td><td>{pct(item.sahjony_split_percent)}</td><td>{item.days_to_buyer==null?'—':`${item.days_to_buyer.toFixed(1)}d`}</td></tr>)}</tbody></table></div>:<div className={styles.empty}><b>No JV submissions yet.</b><span>New structured JV submissions will populate the assignment fee and performance engine automatically.</span></div>}</section>

    <section className={styles.policy}><h2>KPI definitions</h2><p><b>JV gross assignment revenue</b> is the sum of buyer price minus contract price for closed JV deals. <b>Average split</b> is SAHJONY&apos;s documented percentage. <b>Conversion rate</b> is closed JV deals divided by total JV submissions. <b>Days-to-buyer</b> is calendar time from JV submission to the first documented buyer identification. Projected revenue is displayed separately and never counted as realized cash.</p></section>
  </main>;
}

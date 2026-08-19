'use client';

import { useState } from 'react';

const CARD_URL='https://www.sahjony.com/card';

export default function DigitalBusinessCard(){
  const [notice,setNotice]=useState('');
  async function share(){
    const data={title:'Juan Gonzalez · SAHJONY',text:'SAHJONY Real Estate Operations — off-market acquisitions, cash buyers and JV opportunities.',url:CARD_URL};
    try{
      if(navigator.share){await navigator.share(data);return;}
      await navigator.clipboard.writeText(CARD_URL);setNotice('Link copied');
    }catch{}
  }
  async function copy(){try{await navigator.clipboard.writeText(CARD_URL);setNotice('Link copied');}catch{setNotice(CARD_URL)}}
  function saveContact(){
    const vcard=['BEGIN:VCARD','VERSION:3.0','FN:Juan Gonzalez','N:Gonzalez;Juan;;;','ORG:SAHJONY CAPITAL LLC','TITLE:Acquisitions & Real Estate Operations','URL:https://www.sahjony.com','NOTE:Off-market real estate acquisitions, cash-buyer relationships and joint-venture opportunities.','END:VCARD'].join('\r\n');
    const blob=new Blob([vcard],{type:'text/vcard'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='Juan-Gonzalez-SAHJONY.vcf';a.click();URL.revokeObjectURL(url);
  }
  return <main className="cardPage">
    <section className="digitalCard">
      <div className="brandRow"><div className="mark">S</div><div><strong>SAHJONY</strong><span>REAL ESTATE OPERATIONS</span></div></div>
      <div className="identity"><span className="eyebrow">PRIVATE CAPITAL · DIRECT REAL ESTATE</span><h1>Juan Gonzalez</h1><h2>Acquisitions & Real Estate Operations</h2><p>Off-market acquisitions, cash-buyer relationships, wholesale dispositions and joint-venture opportunities.</p></div>
      <div className="ctaGrid"><a href="/sell">Sell a Property</a><a href="/buyers">Cash Buyer Network</a><a href="/joint-venture">Submit a JV Deal</a><a href="/contact">Contact SAHJONY</a></div>
      <div className="shareRow"><button onClick={share}>Share Card</button><button onClick={copy}>Copy Link</button><button onClick={saveContact}>Save Contact</button></div>
      {notice&&<div className="notice">{notice}</div>}
      <footer><span>www.sahjony.com</span><span>SAHJONY CAPITAL LLC</span></footer>
    </section>
    <section className="intro"><span>SHAREABLE DEAL-FLOW CARD</span><h3>One link for sellers, buyers and partners.</h3><p>Send this page by text, email, AirDrop, social media or QR code. It routes every contact into the appropriate SAHJONY intake workflow without exposing the private Owner OS.</p><div className="url">www.sahjony.com/card</div><a className="home" href="/">Visit SAHJONY →</a></section>
    <style jsx>{`
      :global(body){margin:0;background:#050607;color:#f4f4f1;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.cardPage{min-height:100vh;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:56px;align-items:center;padding:64px;box-sizing:border-box;background:radial-gradient(circle at 15% 15%,rgba(190,150,72,.14),transparent 32%),linear-gradient(135deg,#050607 0%,#0a0c0d 100%)}.digitalCard{border:1px solid rgba(218,183,112,.34);background:linear-gradient(145deg,rgba(17,19,20,.98),rgba(7,8,9,.98));border-radius:28px;padding:38px;box-shadow:0 30px 90px rgba(0,0,0,.45);max-width:760px}.brandRow{display:flex;align-items:center;gap:14px}.mark{width:48px;height:48px;border:1px solid #d8b36a;border-radius:50%;display:grid;place-items:center;font-family:Georgia,serif;font-size:26px;color:#e6c27b}.brandRow strong{display:block;letter-spacing:.22em;font-size:15px}.brandRow span{display:block;color:#9e9f9a;font-size:10px;letter-spacing:.18em;margin-top:4px}.identity{padding:68px 0 38px}.eyebrow,.intro>span{font-size:11px;letter-spacing:.19em;color:#d6b16a}.identity h1{font-family:Georgia,serif;font-weight:500;font-size:clamp(44px,7vw,76px);line-height:.98;margin:14px 0 12px}.identity h2{font-weight:500;font-size:18px;color:#d1d2ce;margin:0 0 16px}.identity p{max-width:590px;color:#9fa19d;line-height:1.7;font-size:15px}.ctaGrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.ctaGrid a,.shareRow button{border:1px solid rgba(255,255,255,.12);border-radius:13px;padding:14px 16px;color:#f1f1ed;text-decoration:none;background:rgba(255,255,255,.035);font-size:13px}.ctaGrid a:hover,.shareRow button:hover{border-color:#d6b16a;background:rgba(214,177,106,.08)}.shareRow{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.shareRow button{cursor:pointer;font-family:inherit}.shareRow button:first-child{background:#d6b16a;color:#090a0a;border-color:#d6b16a;font-weight:700}.notice{margin-top:12px;font-size:12px;color:#d6b16a}.digitalCard footer{display:flex;justify-content:space-between;gap:20px;border-top:1px solid rgba(255,255,255,.08);padding-top:22px;margin-top:28px;color:#8d8e8b;font-size:11px;letter-spacing:.08em}.intro{max-width:520px}.intro h3{font-family:Georgia,serif;font-weight:500;font-size:clamp(38px,5vw,64px);line-height:1.03;margin:14px 0 20px}.intro p{color:#a1a29f;line-height:1.75;font-size:16px}.url{display:inline-block;margin:18px 0;padding:12px 15px;border:1px solid rgba(214,177,106,.3);border-radius:12px;color:#dec07f}.home{display:block;margin-top:18px;color:#f0f0ec;text-decoration:none}.home:hover{color:#d6b16a}@media(max-width:900px){.cardPage{grid-template-columns:1fr;padding:28px;gap:34px}.identity{padding:48px 0 30px}.digitalCard{padding:26px}.intro{padding:0 4px 30px}}@media(max-width:540px){.cardPage{padding:16px}.ctaGrid{grid-template-columns:1fr}.digitalCard footer{flex-direction:column}.shareRow button{flex:1 1 120px}}
    `}</style>
  </main>
}

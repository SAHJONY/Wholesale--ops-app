'use client';

import { FormEvent, useState } from 'react';

export default function JointVentureForm(){
  const [status,setStatus]=useState<'idle'|'sending'|'success'|'error'>('idle');
  const [message,setMessage]=useState('');

  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    setStatus('sending');setMessage('');
    const form=event.currentTarget;
    const data=Object.fromEntries(new FormData(form).entries());
    const summary=[
      `JV DEAL SUBMISSION`,
      `Company: ${data.company||'Not provided'}`,
      `Property: ${data.property_address||'Not provided'}, ${data.city||''}, ${data.state||''} ${data.zip_code||''}`,
      `Contract status: ${data.contract_status||'Not provided'}`,
      `Seller/contract price: ${data.contract_price||'Not provided'}`,
      `ARV: ${data.arv||'Not provided'}`,
      `Repairs: ${data.repairs||'Not provided'}`,
      `Desired JV split: ${data.jv_split||'Not provided'}`,
      `Buyer status: ${data.buyer_status||'Not provided'}`,
      `Close date / urgency: ${data.timeline||'Not provided'}`,
      `Notes: ${data.notes||'None'}`,
    ].join('\n');
    const payload={
      name:data.name,
      email:data.email,
      phone:data.phone,
      role:'wholesaler_jv',
      message:summary,
      consent:(form.elements.namedItem('consent') as HTMLInputElement)?.checked?'true':'false',
      website:data.website||'',
    };
    try{
      const response=await fetch('/api/backend/public-intake/partner',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const text=await response.text();let body:any={};try{body=text?JSON.parse(text):{}}catch{body={detail:text}}
      if(!response.ok)throw new Error(body.detail||'Submission could not be completed.');
      setStatus('success');setMessage('JV opportunity received. SAHJONY Operations will review the deal, buyer coverage, economics, and proposed split before any agreement is created.');form.reset();
    }catch(error){setStatus('error');setMessage(error instanceof Error?error.message:'Submission could not be completed.');}
  }

  return <form className="publicForm" onSubmit={submit}>
    <input className="hp" type="text" name="website" tabIndex={-1} autoComplete="off" aria-hidden="true"/>
    <div className="formGrid">
      <label className="field"><span>Your name *</span><input name="name" required/></label>
      <label className="field"><span>Company</span><input name="company"/></label>
      <label className="field"><span>Business email *</span><input name="email" type="email" required/></label>
      <label className="field"><span>Phone *</span><input name="phone" type="tel" required/></label>
      <label className="field fieldWide"><span>Property address *</span><input name="property_address" required/></label>
      <label className="field"><span>City *</span><input name="city" required/></label>
      <label className="field"><span>State *</span><input name="state" maxLength={2} required/></label>
      <label className="field"><span>ZIP code *</span><input name="zip_code" required/></label>
      <label className="field"><span>Contract status *</span><select name="contract_status" required defaultValue=""><option value="" disabled>Select</option><option value="under_contract">Under contract / assignable</option><option value="direct_to_seller">Direct to seller, not yet contracted</option><option value="marketing_interest">Marketing / co-wholesale interest only</option></select></label>
      <label className="field"><span>Seller / contract price</span><input name="contract_price" inputMode="decimal"/></label>
      <label className="field"><span>ARV</span><input name="arv" inputMode="decimal"/></label>
      <label className="field"><span>Estimated repairs</span><input name="repairs" inputMode="decimal"/></label>
      <label className="field"><span>Desired JV split</span><input name="jv_split" placeholder="Example: 50/50"/></label>
      <label className="field"><span>Buyer status</span><select name="buyer_status" defaultValue=""><option value="">Select</option><option value="need_buyer">Need SAHJONY buyer/disposition support</option><option value="buyer_identified">Buyer identified</option><option value="multiple_buyers">Multiple buyers available</option></select></label>
      <label className="field"><span>Closing timeline</span><input name="timeline" placeholder="Example: close by Sept 5"/></label>
      <label className="field fieldWide"><span>Deal notes</span><textarea name="notes" rows={5} placeholder="Condition, access, title issues, comps, seller situation, assignment restrictions, or anything material."/></label>
    </div>
    <label className="consent"><input type="checkbox" name="consent" required/> <span>I authorize SAHJONY to contact me about this JV submission. I understand no JV, agency, purchase, assignment, or compensation agreement exists unless separately approved in writing.</span></label>
    <button className="primaryButton" type="submit" disabled={status==='sending'}>{status==='sending'?'Submitting…':'Submit JV opportunity'}</button>
    {message&&<p className={status==='error'?'formMessage errorText':'formMessage'} role="status">{message}</p>}
  </form>;
}

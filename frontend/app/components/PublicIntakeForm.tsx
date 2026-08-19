'use client';

import { FormEvent, useState } from 'react';

type Field={name:string;label:string;type?:string;required?:boolean;placeholder?:string;options?:{value:string;label:string}[];textarea?:boolean};

type Props={kind:'seller'|'buyer'|'partner'|'contact';fields:Field[];submitLabel:string;successMessage:string};

export default function PublicIntakeForm({kind,fields,submitLabel,successMessage}:Props){
  const [status,setStatus]=useState<'idle'|'sending'|'success'|'error'>('idle');
  const [message,setMessage]=useState('');

  async function submit(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    setStatus('sending');setMessage('');
    const form=event.currentTarget;
    const data=Object.fromEntries(new FormData(form).entries());
    data.consent=(form.elements.namedItem('consent') as HTMLInputElement)?.checked?'true':'false';
    try{
      const response=await fetch(`/api/backend/public-intake/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      const text=await response.text();let body:any={};try{body=text?JSON.parse(text):{}}catch{body={detail:text}}
      if(!response.ok)throw new Error(body.detail||'Submission could not be completed.');
      setStatus('success');setMessage(successMessage);form.reset();
    }catch(error){
      setStatus('error');setMessage(error instanceof Error?error.message:'Submission could not be completed.');
    }
  }

  return <form className="publicForm" onSubmit={submit}>
    <input className="hp" type="text" name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" />
    <div className="formGrid">
      {fields.map(field=><label key={field.name} className={field.textarea?'field fieldWide':'field'}>
        <span>{field.label}{field.required?' *':''}</span>
        {field.options?<select name={field.name} required={field.required} defaultValue=""><option value="" disabled>Select</option>{field.options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>:field.textarea?<textarea name={field.name} required={field.required} placeholder={field.placeholder} rows={5}/>:<input name={field.name} type={field.type||'text'} required={field.required} placeholder={field.placeholder}/>} 
      </label>)}
    </div>
    <label className="consent"><input type="checkbox" name="consent" required/> <span>I authorize SAHJONY to contact me to respond to this submission. This does not authorize unrelated automated marketing.</span></label>
    <button className="primaryButton" type="submit" disabled={status==='sending'}>{status==='sending'?'Submitting…':submitLabel}</button>
    {message&&<p className={status==='error'?'formMessage errorText':'formMessage'} role="status">{message}</p>}
  </form>;
}

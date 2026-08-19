import PublicIntakeForm from '../components/PublicIntakeForm';

const fields=[
  {name:'name',label:'Your name',required:true},
  {name:'email',label:'Email',type:'email',required:true},
  {name:'phone',label:'Phone',type:'tel'},
  {name:'message',label:'How can we help?',required:true,textarea:true,placeholder:'Tell us what you need and include the property, deal, market, or business context when relevant.'}
];

export default function ContactPage(){return <main className="publicShell">
  <nav className="publicNav"><a className="publicBrand" href="/">SAHJONY<small>REAL ESTATE OPERATIONS</small></a><div className="publicLinks"><a href="/sell">Sell a Property</a><a href="/buyers">Cash Buyers</a><a href="/partners">Partners</a><a className="loginPill" href="/owner-access">Owner Login</a></div></nav>
  <header className="publicPageHeader"><span className="sectionEyebrow">CONTACT SAHJONY</span><h1>Route the question to the right desk.</h1><p>Use this form for general business questions that do not fit Seller, Buyer, or Partner intake. The submission enters the Support queue and can be reassigned internally without exposing private operating data.</p></header>
  <section className="intakeWrap"><PublicIntakeForm kind="contact" fields={fields} submitLabel="Send inquiry" successMessage="Inquiry received. SAHJONY Support will review it and route it to the appropriate department."/><p className="publicNote">For property sales, use Seller Intake. For investment buying criteria, use Cash Buyer Network. This helps us respond through the correct operating workflow.</p></section>
</main>}

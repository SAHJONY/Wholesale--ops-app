import PublicIntakeForm from '../components/PublicIntakeForm';

const fields=[
  {name:'name',label:'Your name',required:true},
  {name:'email',label:'Business email',type:'email',required:true},
  {name:'phone',label:'Phone',type:'tel'},
  {name:'role',label:'Partner type',required:true,options:[
    {value:'agent_broker',label:'Agent / Broker'},
    {value:'title_closing',label:'Title / Closing'},
    {value:'contractor',label:'Contractor / Vendor'},
    {value:'lender_capital',label:'Lender / Capital Partner'},
    {value:'wholesaler_referral',label:'Wholesaler / Referral Partner'},
    {value:'other',label:'Other professional'}
  ]},
  {name:'message',label:'How would you like to work with SAHJONY?',required:true,textarea:true,placeholder:'Describe the opportunity, referral, service, market, or transaction support you are contacting us about.'}
];

export default function PartnersPage(){return <main className="publicShell">
  <nav className="publicNav"><a className="publicBrand" href="/">SAHJONY<small>REAL ESTATE OPERATIONS</small></a><div className="publicLinks"><a href="/sell">Sell a Property</a><a href="/buyers">Cash Buyers</a><a href="/joint-venture">Joint Venture</a><a href="/contact">Contact</a><a className="loginPill" href="/owner-access">Owner Login</a></div></nav>
  <header className="publicPageHeader"><span className="sectionEyebrow">TRANSACTION PARTNERS</span><h1>Bring the right expertise into the transaction.</h1><p>Agents, brokers, title and closing professionals, contractors, lenders, wholesalers, and qualified service providers can submit a partnership or transaction-routing inquiry. Wholesalers with a specific deal should use the dedicated Joint Venture intake so property economics and disposition needs are captured correctly.</p><div className="heroActions"><a className="primaryButton" href="/joint-venture">Submit a JV deal</a></div></header>
  <section className="intakeWrap"><PublicIntakeForm kind="partner" fields={fields} submitLabel="Submit partner inquiry" successMessage="Partner inquiry received. SAHJONY Operations will review and route it to the appropriate department."/><p className="publicNote">A submission does not create an agency, brokerage, vendor, lending, title, joint venture, or other contractual relationship. Any engagement requires separate written approval.</p></section>
</main>}

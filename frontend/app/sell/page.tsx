import PublicIntakeForm from '../components/PublicIntakeForm';

const fields=[
{name:'name',label:'Your name',required:true},{name:'phone',label:'Phone',type:'tel',required:true},{name:'email',label:'Email',type:'email'},
{name:'address',label:'Property street address',required:true},{name:'city',label:'City',required:true},{name:'state',label:'State',required:true,placeholder:'TX'},{name:'zip_code',label:'ZIP code',required:true},
{name:'property_type',label:'Property type',options:[{value:'single_family',label:'Single-family'},{value:'multi_family',label:'Multi-family'},{value:'vacant_land',label:'Vacant land'},{value:'other',label:'Other'}]},
{name:'timeline_days',label:'Desired timeline',options:[{value:'7',label:'Within 7 days'},{value:'14',label:'Within 2 weeks'},{value:'30',label:'Within 30 days'},{value:'60',label:'Within 60 days'},{value:'90',label:'Flexible / 90+ days'}]},
{name:'asking_price',label:'Price expectation',type:'number',placeholder:'Optional'},
{name:'condition',label:'Property condition / repairs',textarea:true,placeholder:'Tell us about repairs, deferred maintenance, occupancy, or anything we should know.'},
{name:'motivation',label:'Why are you considering selling?',textarea:true,placeholder:'Optional, but it helps us understand the situation.'}
];

export default function SellPage(){return <main className="publicShell"><nav className="publicNav"><a className="publicBrand" href="/">SAHJONY<small>REAL ESTATE OPERATIONS</small></a><div className="publicLinks"><a href="/buyers">Cash Buyers</a><a href="/partners">Partners</a><a href="/contact">Contact</a><a className="loginPill" href="/owner-access">Owner Login</a></div></nav><header className="publicPageHeader"><span className="sectionEyebrow">SELL A PROPERTY</span><h1>Start with the property and your timeline.</h1><p>Submit the basic facts. SAHJONY Acquisitions will review the opportunity before discussing pricing or terms. Submission does not create a contract or guarantee an offer.</p></header><section className="intakeWrap"><PublicIntakeForm kind="seller" fields={fields} submitLabel="Submit property" successMessage="Property received. Acquisitions will review the submission and respond using the contact information you provided."/><p className="publicNote">We evaluate properties on an as-is basis. Any valuation, offer, title position, payoff amount, or closing timeline remains subject to verification and written agreement.</p></section></main>}

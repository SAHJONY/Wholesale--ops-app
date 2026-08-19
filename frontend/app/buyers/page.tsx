import PublicIntakeForm from '../components/PublicIntakeForm';

const fields=[
{name:'name',label:'Buyer name',required:true},{name:'company',label:'Company'},{name:'phone',label:'Phone',type:'tel',required:true},{name:'email',label:'Email',type:'email'},
{name:'zip_codes',label:'Target ZIP codes',required:true,placeholder:'77051, 77084, 77021'},{name:'asset_types',label:'Asset types',placeholder:'single_family, multi_family, land'},
{name:'min_price',label:'Minimum purchase price',type:'number'},{name:'max_price',label:'Maximum purchase price',type:'number'},{name:'max_rehab',label:'Maximum rehab',type:'number'},{name:'closing_days',label:'Typical closing days',type:'number',placeholder:'14'},
{name:'pof_ready',label:'Proof of funds status',options:[{value:'true',label:'Ready to provide'},{value:'false',label:'Not ready yet'}]}
];

export default function BuyersPage(){return <main className="publicShell"><nav className="publicNav"><a className="publicBrand" href="/">SAHJONY<small>REAL ESTATE OPERATIONS</small></a><div className="publicLinks"><a href="/sell">Sell a Property</a><a href="/partners">Partners</a><a href="/contact">Contact</a><a className="loginPill" href="/owner-access">Owner Login</a></div></nav><header className="publicPageHeader"><span className="sectionEyebrow">CASH BUYER NETWORK</span><h1>Tell us exactly what you buy.</h1><p>Register a buying box for off-market opportunities. Proof of funds is never marked verified from a web submission; SAHJONY Dispositions reviews it separately before deal-ready status.</p></header><section className="intakeWrap"><PublicIntakeForm kind="buyer" fields={fields} submitLabel="Join buyer network" successMessage="Buyer profile received. Dispositions will review your buying box and proof-of-funds status."/><p className="publicNote">Registration does not guarantee deal access. Opportunity distribution depends on verified buying criteria, availability, compliance, and transaction fit.</p></section></main>}

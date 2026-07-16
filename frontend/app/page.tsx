const modules = [
  ["Distressed SFR", "Score vacant, inherited, code-violation and high-equity homes."],
  ["Seller Acquisition", "Bland.ai inbound and outbound calls with lead qualification."],
  ["Buyer Intelligence", "Rank cash buyers by live buy box, reliability and proof of funds."],
  ["Driving for Dollars", "Capture GPS leads and visual distress observations."],
  ["Underwriting", "Calculate ARV, repairs, MAO, assignment spread and commercial value."],
  ["Disposition", "Launch buyer campaigns, collect offers and track closing probability."],
];

const DEFAULT_API_URL = "https://backend-pi-opal-65.vercel.app";

async function getStats() {
  const url = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
  try {
    const response = await fetch(`${url}/dashboard`, { cache: "no-store" });
    if (!response.ok) throw new Error(`API unavailable: ${response.status}`);
    return { ...(await response.json()), api_online: true };
  } catch {
    return { total_leads: 0, hot_leads: 0, buyers: 0, calls: 0, api_online: false };
  }
}

export default async function Home() {
  const stats = await getStats();
  return (
    <main>
      <aside>
        <div className="brand">SAHJONY</div>
        <p>Wholesale Operations</p>
        <nav>
          {['Command Center','Leads','Distressed SFR','Deals','Cash Buyers','Calls','Driving for Dollars','Campaigns','Analytics','Integrations'].map((item) => <a key={item}>{item}</a>)}
        </nav>
      </aside>
      <section className="content">
        <header>
          <div><span className="eyebrow">AUTONOMOUS WORKFORCE</span><h1>Wholesale Command Center</h1><p>Residential and commercial deal operations in one system.</p><p className="apiStatus">API: {stats.api_online ? "Connected" : "Offline"}</p></div>
          <button>+ Add Lead</button>
        </header>
        <div className="stats">
          {[
            ["Total leads", stats.total_leads],
            ["Hot leads", stats.hot_leads],
            ["Qualified buyers", stats.buyers],
            ["Calls logged", stats.calls],
          ].map(([label,value]) => <article key={label as string}><span>{label}</span><strong>{value}</strong></article>)}
        </div>
        <div className="sectionTitle"><h2>Operating Modules</h2><span>Human approval required for binding actions</span></div>
        <div className="grid">
          {modules.map(([title, description], index) => (
            <article className="module" key={title}>
              <div className="number">0{index + 1}</div><h3>{title}</h3><p>{description}</p><a>Open module →</a>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

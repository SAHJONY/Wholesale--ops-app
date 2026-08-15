'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import styles from './deal-factory.module.css';

type Skill = { id: string; name: string; risk: string; purpose?: string; inputs?: string[]; outputs?: string[] };
type Opportunity = {
  property: { id: number; address: string; city: string; state: string; zip_code: string; property_type: string; asking_price?: number; arv?: number; repairs?: number; distress_signals?: string[] };
  owner: { name?: string; type: string; mailing_address?: string; verification_status: string; confidence: number };
  deed: { apn?: string; last_sale_date?: string; last_sale_price?: number; deed_type?: string; instrument?: string };
  distress: { signals: string[]; count: number };
  economics: { screening_factor: number; screening_buyer_price?: number; seller_price?: number; projected_screening_spread?: number; meets_10k_target: boolean; authority: string };
  buyers: Array<{ buyer_id?: number; name?: string; response_probability?: number; fit_score?: number; reasons?: string[] }>;
  evidence: { score: number; sources: Array<{ provider: string; reference?: string; confidence: number; verification_status: string }>; source_count: number; open_conflicts: string[]; missing: string[] };
  decision: { ready_for_promotion: boolean; risk_score: number; next_action: string; human_offer_approval_required: boolean; legal_financial_actions_autonomous: boolean };
};
type FactoryResponse = {
  generated_at: string;
  mode: string;
  summary: { prospects: number; promotion_ready: number; individual_owned: number; meets_10k_screen: number; buyers: number; promoted_deals: number };
  opportunities: Opportunity[];
  skills: Skill[];
  operating_flow: string[];
};
type SkillsResponse = { skills: Skill[]; policy: Record<string, unknown> };

function money(value?: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value || 0);
}
function pct(value?: number) { return `${Math.round(Number(value || 0) * 100)}%`; }
function label(value = '') { return value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()); }

export default function DealFactoryPage() {
  const [factory, setFactory] = useState<FactoryResponse | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [state, setState] = useState('');
  const [onlyReady, setOnlyReady] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const request = useCallback(async (path: string) => {
    const response = await fetch(`/api/backend${path}`, { cache: 'no-store', headers: { Authorization: 'Bearer cookie-session' } });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      window.location.replace('/login?returnTo=/owner/deal-factory');
      throw new Error('Owner session required');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [factoryData, skillsData] = await Promise.all([
        request('/wholesale-os/deal-factory') as Promise<FactoryResponse>,
        request('/wholesale-os/skills') as Promise<SkillsResponse>,
      ]);
      setFactory(factoryData);
      setSkills(Array.isArray(skillsData.skills) ? skillsData.skills : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load the Deal Factory');
    } finally { setLoading(false); }
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  const opportunities = useMemo(() => {
    const rows = factory?.opportunities || [];
    return rows.filter(item => {
      if (state && item.property.state?.toUpperCase() !== state.toUpperCase()) return false;
      if (onlyReady && !item.decision.ready_for_promotion) return false;
      return true;
    });
  }, [factory, state, onlyReady]);

  const spread = useMemo(() => opportunities.reduce((sum, item) => sum + Math.max(0, Number(item.economics.projected_screening_spread || 0)), 0), [opportunities]);
  const selectedDeal = opportunities.find(item => item.property.id === selected) || null;

  return <main className={styles.page}>
    <header className={styles.hero}>
      <div>
        <span>SAHJONY WHOLESALE OS · NATIONWIDE DEAL FACTORY</span>
        <h1>Find, verify and analyze real wholesale opportunities from source-backed data.</h1>
        <p>Every opportunity is separated into verified facts, screening economics, missing evidence and human-controlled next actions. No invented comps. No guessed owners. No autonomous contracts.</p>
      </div>
      <div className={styles.actions}>
        <a href="/owner/public-data">Find public sources</a>
        <a href="/owner/deal-intelligence">Underwrite with comps</a>
        <button onClick={() => void load()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh Deal Factory'}</button>
      </div>
    </header>

    {error && <div className={styles.error}>{error}</div>}

    <section className={styles.kpis}>
      <article><span>Prospects analyzed</span><strong>{factory?.summary.prospects || 0}</strong><small>Workspace properties</small></article>
      <article><span>Individual-owned</span><strong>{factory?.summary.individual_owned || 0}</strong><small>Entity owners excluded from your target</small></article>
      <article><span>$10K+ screens</span><strong>{factory?.summary.meets_10k_screen || 0}</strong><small>Screening only until verified</small></article>
      <article className={styles.profit}><span>Visible spread</span><strong>{money(spread)}</strong><small>Across current filtered opportunities</small></article>
      <article><span>Promotion ready</span><strong>{factory?.summary.promotion_ready || 0}</strong><small>Owner + evidence + economics gate</small></article>
      <article><span>Verified buyers</span><strong>{factory?.summary.buyers || 0}</strong><small>Buyer network available to match</small></article>
    </section>

    <section className={styles.flowPanel}>
      <div className={styles.sectionHeader}><div><span>OPERATING SYSTEM</span><h2>One workflow from public record to assignment fee</h2></div></div>
      <div className={styles.flow}>{(factory?.operating_flow || []).map((step, index) => <div key={step}><b>{String(index + 1).padStart(2, '0')}</b><span>{step}</span></div>)}</div>
    </section>

    <section className={styles.workspace}>
      <div className={styles.listPanel}>
        <div className={styles.sectionHeader}>
          <div><span>LIVE WORKSPACE INTELLIGENCE</span><h2>Ranked opportunities</h2></div>
          <div className={styles.filters}>
            <label>State<input value={state} onChange={event => setState(event.target.value.toUpperCase().slice(0, 2))} placeholder="ALL" /></label>
            <label className={styles.check}><input type="checkbox" checked={onlyReady} onChange={event => setOnlyReady(event.target.checked)} /> Promotion ready only</label>
          </div>
        </div>

        <div className={styles.table}>
          <div className={styles.tableHead}><span>Property / owner</span><span>Evidence</span><span>Economics</span><span>Buyer demand</span><span>Decision</span></div>
          {opportunities.map(item => <button type="button" key={item.property.id} className={`${styles.row} ${selected === item.property.id ? styles.selected : ''}`} onClick={() => setSelected(item.property.id)}>
            <span className={styles.propertyCell}><b>{item.property.address}</b><small>{item.property.city}, {item.property.state} {item.property.zip_code}</small><em>{item.owner.name || 'Owner not verified'} · {item.owner.type}</em></span>
            <span><b>{item.evidence.score}%</b><small>{item.evidence.source_count} source{item.evidence.source_count === 1 ? '' : 's'}</small><em>{item.evidence.open_conflicts.length ? `${item.evidence.open_conflicts.length} conflict(s)` : 'No open conflicts'}</em></span>
            <span><b className={item.economics.meets_10k_target ? styles.moneyGood : ''}>{money(item.economics.projected_screening_spread)}</b><small>Ask {money(item.property.asking_price)} · ARV {money(item.property.arv)}</small><em>Repairs {money(item.property.repairs)}</em></span>
            <span><b>{item.buyers.length}</b><small>matched buyers</small><em>{item.buyers[0]?.response_probability ? `${pct(item.buyers[0].response_probability)} top response` : 'Buyer demand unproven'}</em></span>
            <span><b className={item.decision.ready_for_promotion ? styles.ready : styles.pending}>{item.decision.ready_for_promotion ? 'READY' : 'VERIFY'}</b><small>Risk {item.decision.risk_score}/100</small><em>{item.decision.next_action}</em></span>
          </button>)}
          {!loading && opportunities.length === 0 && <div className={styles.empty}><b>No opportunities match this filter.</b><span>Ingest or enrich real properties, then refresh the Deal Factory.</span></div>}
        </div>
      </div>

      <aside className={styles.detailPanel}>
        {selectedDeal ? <>
          <div className={styles.detailTitle}><span>PROPERTY ANALYSIS</span><h2>{selectedDeal.property.address}</h2><p>{selectedDeal.decision.next_action}</p></div>

          <section><h3>Owner + deed</h3><dl>
            <div><dt>Owner of record</dt><dd>{selectedDeal.owner.name || 'Not verified'}</dd></div>
            <div><dt>Owner type</dt><dd>{label(selectedDeal.owner.type)}</dd></div>
            <div><dt>APN</dt><dd>{selectedDeal.deed.apn || 'Pending'}</dd></div>
            <div><dt>Latest transfer</dt><dd>{selectedDeal.deed.last_sale_date || 'Pending'} {selectedDeal.deed.last_sale_price ? `· ${money(selectedDeal.deed.last_sale_price)}` : ''}</dd></div>
          </dl></section>

          <section><h3>Economics</h3><dl>
            <div><dt>Asking / seller price</dt><dd>{money(selectedDeal.property.asking_price)}</dd></div>
            <div><dt>ARV</dt><dd>{money(selectedDeal.property.arv)}</dd></div>
            <div><dt>Repairs</dt><dd>{money(selectedDeal.property.repairs)}</dd></div>
            <div><dt>70% screen buyer price</dt><dd>{money(selectedDeal.economics.screening_buyer_price)}</dd></div>
            <div><dt>Screening spread</dt><dd className={styles.moneyGood}>{money(selectedDeal.economics.projected_screening_spread)}</dd></div>
          </dl><p className={styles.disclaimer}>The 70% factor is a screening heuristic, not an offer or appraisal. Use source-backed comps and actual buyer constraints before contracting.</p></section>

          <section><h3>Distress stack</h3><div className={styles.badges}>{selectedDeal.distress.signals.length ? selectedDeal.distress.signals.map(signal => <span key={signal}>{label(signal)}</span>) : <em>No verified distress signals captured.</em>}</div></section>

          <section><h3>Evidence gaps</h3><ul>{selectedDeal.evidence.missing.length ? selectedDeal.evidence.missing.map(gap => <li key={gap}>{gap}</li>) : <li>No current material evidence gaps.</li>}</ul></section>

          <section><h3>Buyer matches</h3><div className={styles.buyers}>{selectedDeal.buyers.length ? selectedDeal.buyers.slice(0, 4).map((buyer, index) => <div key={`${buyer.buyer_id}-${index}`}><b>{buyer.name || `Buyer #${buyer.buyer_id}`}</b><span>{pct(buyer.response_probability)} response probability</span><small>{(buyer.reasons || []).slice(0, 2).join(' · ') || 'Buy-box model match'}</small></div>) : <p>No buyer demand verified yet.</p>}</div></section>

          <div className={styles.detailActions}><a href="/owner/real-deals">Open Real Deals</a><a href="/owner/deal-intelligence">Run comp underwriting</a><a href="/owner/buyer-intake">Review buyers</a></div>
        </> : <div className={styles.placeholder}><b>Select an opportunity.</b><span>You will see owner, deed, economics, evidence gaps, distress and buyer demand here.</span></div>}
      </aside>
    </section>

    <section className={styles.skillsPanel}>
      <div className={styles.sectionHeader}><div><span>WHOLESALE SKILLS</span><h2>Built-in analysis capabilities</h2><p>These skills compose the same workflow used to find and evaluate real deals, but every high-risk action remains supervised.</p></div></div>
      <div className={styles.skillGrid}>{skills.map((skill, index) => <article key={skill.id}><span>{String(index + 1).padStart(2, '0')}</span><h3>{skill.name}</h3><p>{skill.purpose || 'Source-grounded wholesale operating capability.'}</p><footer>{label(skill.risk)}</footer></article>)}</div>
    </section>
  </main>;
}

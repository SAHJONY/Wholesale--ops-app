'use client';

import { useCallback, useEffect, useState } from 'react';
import styles from '../owner.module.css';

const API = '/api/deal-intelligence';
// The session cookie is HttpOnly and middleware attaches it to same-origin
// /api/* requests, so this page never sees or stores a token.

type Priority = { action: string; rationale: string; urgency: string };
type Analysis = {
  headline?: string;
  confidence?: number;
  priorities?: Priority[];
  risks_to_revenue?: string[];
  capacity_notes?: string[];
  source?: string;
  fallback_reason?: string;
};
type Bottleneck = {
  stage: string;
  deals: number;
  stalled_deals: number;
  expected_value_held: number;
  typical_dwell_days: number;
  advance_probability: number;
  severity: number;
};
type StalledDeal = { deal_id: number; stage: string; days_in_stage: number | null; expected_value: number };
type Forecast = {
  expected_revenue: number;
  nominal_pipeline_value: number;
  revenue_interval: { low: number; high: number };
  overstatement_vs_nominal: number;
  bottlenecks: Bottleneck[];
  stalled_deals: StalledDeal[];
};
type Attribution = { feature: string; share: number; direction: string };
type ScoredLead = {
  lead_id: number;
  seller_name?: string;
  address?: string;
  probability: number;
  score: number;
  band: string;
  legacy_score: number;
  model_fitted: boolean;
  attribution: Attribution[];
};
type Model = {
  fitted: boolean;
  training_rows: number;
  positive_rows: number;
  base_rate: number;
  blend_weight: number;
  metrics: Record<string, number>;
  notes: string[];
};
type Briefing = {
  analysis?: Analysis;
  forecast?: Forecast;
  leads?: { total: number; priority: number; top: ScoredLead[] };
  pending_approvals?: number;
  scoring_model?: Model;
  detail?: string;
  offline?: boolean;
};

const money = (value: number | undefined) => `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const percent = (value: number | undefined) => `${(Number(value || 0) * 100).toFixed(1)}%`;

export default function DealIntelligencePage() {
  const [data, setData] = useState<Briefing>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API}/briefing`, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
      });
      const text = await response.text();
      let body: any = {};
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          body = { detail: text };
        }
      }
      if (response.status === 401 || response.status === 403) {
        location.replace('/login?returnTo=/owner/deal-intelligence');
        return;
      }
      if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
      setData(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load decision intelligence');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const analysis = data.analysis;
  const forecast = data.forecast;
  const model = data.scoring_model;
  const deterministic = analysis?.source === 'deterministic';

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>DECISION INTELLIGENCE</span>
          <h1>Underwriting &amp; Portfolio Intelligence</h1>
          <p>
            Probability-weighted revenue, outcome-calibrated lead scoring, and structured deal
            reasoning. Every recommendation is a proposal for approval, never a completed action.
          </p>
        </div>
        <div className={styles.actions}>
          <button onClick={() => void load()} disabled={loading}>Refresh</button>
          <a className={styles.linkButton} href="/owner/real-estate-intelligence">Intelligence Platform</a>
          <a className={styles.linkButton} href="/owner/disposition">Disposition</a>
          <a className={styles.linkButton} href="/owner">Control Plane</a>
        </div>
      </header>

      {error && <div className={styles.error}>{error}</div>}
      {data.offline && <div className={styles.notice}>{data.detail}</div>}
      {deterministic && (
        <div className={styles.notice}>
          Reasoning engine: deterministic rules ({analysis?.fallback_reason}). Set ANTHROPIC_API_KEY
          to enable Claude-backed structured analysis.
        </div>
      )}

      <section className={styles.metrics}>
        <article><span>Expected revenue</span><strong>{money(forecast?.expected_revenue)}</strong></article>
        <article><span>Nominal pipeline</span><strong>{money(forecast?.nominal_pipeline_value)}</strong></article>
        <article><span>Overstatement</span><strong>{money(forecast?.overstatement_vs_nominal)}</strong></article>
        <article><span>Priority leads</span><strong>{data.leads?.priority || 0}</strong></article>
        <article><span>Pending approvals</span><strong>{data.pending_approvals || 0}</strong></article>
      </section>

      {analysis && (
        <section className={styles.cardWide}>
          <div className={styles.cardHeader}>
            <div>
              <span className={styles.eyebrow}>OPERATING PRIORITIES</span>
              <h2>{analysis.headline || 'Pipeline assessment'}</h2>
            </div>
            <strong>{analysis.confidence != null ? `${analysis.confidence}% confidence` : ''}</strong>
          </div>
          <div className={styles.list}>
            {(analysis.priorities || []).map((item, index) => (
              <div key={index}>
                <span>
                  <b>{item.action}</b>
                  <small>{item.rationale}</small>
                </span>
                <strong>{item.urgency.replaceAll('_', ' ').toUpperCase()}</strong>
              </div>
            ))}
            {(analysis.risks_to_revenue || []).map((risk, index) => (
              <div key={`risk-${index}`}>
                <span><b>Revenue risk</b><small>{risk}</small></span>
                <strong>RISK</strong>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={styles.cardWide}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>REVENUE FORECAST</span>
            <h2>Probability-weighted pipeline</h2>
          </div>
          <strong>
            {money(forecast?.revenue_interval?.low)} – {money(forecast?.revenue_interval?.high)}
          </strong>
        </div>
        <div className={styles.list}>
          {(forecast?.bottlenecks || []).map((item) => (
            <div key={item.stage}>
              <span>
                <b>{item.stage.replaceAll('_', ' ')} · {item.deals} deal(s)</b>
                <small>
                  {money(item.expected_value_held)} held · typical dwell {item.typical_dwell_days}d ·
                  advance {percent(item.advance_probability)} · {item.stalled_deals} stalled
                </small>
              </span>
              <strong>{Math.round(item.severity).toLocaleString()}</strong>
            </div>
          ))}
          {!forecast?.bottlenecks?.length && <p>No open deals to forecast against yet.</p>}
        </div>
      </section>

      {!!forecast?.stalled_deals?.length && (
        <section className={styles.cardWide}>
          <div className={styles.cardHeader}>
            <div>
              <span className={styles.eyebrow}>STALLED</span>
              <h2>Deals not advancing</h2>
            </div>
            <strong>{forecast.stalled_deals.length}</strong>
          </div>
          <div className={styles.list}>
            {forecast.stalled_deals.map((deal) => (
              <div key={deal.deal_id}>
                <span>
                  <b>Deal #{deal.deal_id} · {deal.stage}</b>
                  <small>{deal.days_in_stage ?? '—'} days without advancing</small>
                </span>
                <strong>{money(deal.expected_value)}</strong>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className={styles.cardWide}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.eyebrow}>RANKED LEADS</span>
            <h2>Calibrated conversion probability</h2>
          </div>
          <strong>{data.leads?.total || 0}</strong>
        </div>
        <div className={styles.list}>
          {(data.leads?.top || []).map((lead) => (
            <div key={lead.lead_id}>
              <span>
                <b>{lead.seller_name || `Lead #${lead.lead_id}`} · {lead.band.toUpperCase()}</b>
                <small>{lead.address || 'No address on file'} · legacy score {lead.legacy_score}</small>
                <small>
                  {lead.attribution.slice(0, 3).map((a) => `${a.feature.replaceAll('_', ' ')} ${a.direction} (${a.share}%)`).join(' · ')}
                </small>
              </span>
              <strong>{percent(lead.probability)}</strong>
            </div>
          ))}
          {!data.leads?.top?.length && <p>No leads are linked to this workspace yet.</p>}
        </div>
      </section>

      {model && (
        <section className={styles.cardWide}>
          <div className={styles.cardHeader}>
            <div>
              <span className={styles.eyebrow}>SCORING MODEL</span>
              <h2>{model.fitted ? 'Fitted on closed outcomes' : 'Prior weighting'}</h2>
            </div>
            <strong>{model.training_rows} outcome(s)</strong>
          </div>
          <div className={styles.list}>
            <div>
              <span>
                <b>Training data</b>
                <small>
                  {model.positive_rows} converted of {model.training_rows} resolved · base rate{' '}
                  {percent(model.base_rate)} · fitted model carries {percent(model.blend_weight)} of the score
                </small>
              </span>
              <strong>{model.fitted ? 'FITTED' : 'PRIOR'}</strong>
            </div>
            {model.fitted && (
              <div>
                <span>
                  <b>In-sample calibration</b>
                  <small>
                    Brier {model.metrics.brier_score} · log loss {model.metrics.log_loss} · AUC{' '}
                    {model.metrics.auc} — in-sample, not held out
                  </small>
                </span>
                <strong>AUC {model.metrics.auc}</strong>
              </div>
            )}
            {model.notes.map((note, index) => (
              <div key={index}>
                <span><b>Model note</b><small>{note}</small></span>
                <strong>NOTE</strong>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

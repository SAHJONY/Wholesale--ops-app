# Decision Intelligence Layer

The decision-intelligence layer replaces the platform's fixed-formula heuristics
with calibrated, uncertainty-aware models. Each engine is pure Python,
deterministic for a given input, and adds no numeric dependencies — the deploy
footprint is unchanged.

| Engine | Module | Replaces |
|---|---|---|
| Comparable-sales valuation + Monte Carlo underwriting | `app/valuation.py` | `services.calculate_mao` (`arv * 0.70 - repairs - fee`) |
| Claude structured-output orchestrator | `app/decision_intelligence.py` | The unimplemented backlog item in `ARCHITECTURE.md` |
| Outcome-calibrated lead scoring | `app/adaptive_scoring.py` | `services.lead_score` (fixed 30/25/25/20 weights) |
| Buyer response model + portfolio assignment | `app/buyer_intelligence.py` | `services.match_buyer` (fixed point additions) |
| Pipeline conversion and revenue forecasting | `app/pipeline_forecast.py` | `operating_system.executive_brief` raw fee sum |
| Free public market data (Census ACS, FHFA HPI) | `app/market_data.py` | `valuation.DEFAULT_MONTHLY_APPRECIATION` hardcoded guess |

## Valuation and underwriting

ARV is derived from comparable sales rather than taken as an operator input.
Each comparable is run through a sales-comparison grid — market-time, size,
bed/bath, age, and condition adjustments — then weighted by a similarity kernel
over distance, recency, size delta, and adjustment magnitude. Comparables
needing more than 35% net adjustment are excluded; the rest are screened for
outliers by weighted median absolute deviation.

The result carries a 95% confidence interval derived from the Kish effective
sample size, so three near-identical comps do not masquerade as strong evidence.
**If no comparable survives, the engine raises rather than returning a number.**

That interval then feeds a Monte Carlo simulation over ARV, repair overrun
(right-skewed — budgets miss high), and buyer yield. Instead of one MAO it
returns a distribution, and `recommended_max_offer` is the contract price at
which the assignment still clears the target fee in the requested share of
simulated outcomes (default 75%). This is what the 70% rule approximates, except
it adapts to how uncertain the specific deal actually is.

```
POST /deal-intelligence/underwrite
{
  "subject": {"sqft": 1500, "bedrooms": 3, "bathrooms": 2, "condition": "moderate",
              "distress_signals": ["roof_damage"]},
  "comparables": [{"address": "...", "sale_price": 250000, "sale_date": "2026-05-01",
                   "sqft": 1520, "distance_miles": 0.3, "condition": "good"}],
  "target_fee": 15000,
  "confidence_target": 0.75
}
```

Comparables must come from a licensed or public data source supplied by the
caller. None are inferred — an invented comparable would corrupt everything
downstream of it. See `FREE_DATA_SOURCES.md` for why no free national source of
comparable sales exists and what the realistic alternatives cost.

The market-time adjustment is driven by measured FHFA appreciation for the
subject's ZIP, metro, or state rather than a constant, and the resulting ARV is
screened against the Census median home value for the area — which catches
internally consistent comparables drawn from the wrong neighbourhood, and
decimal errors in a sale price. When no index is reachable the underwriting still
completes, but the rate is labelled `measured: false` and the valuation carries a
warning.

## Claude orchestrator

`ARCHITECTURE.md` listed an "Anthropic structured-output orchestrator" as
backlog and `fable5-plan.yaml` named Anthropic as the orchestrator provider, but
the `anthropic` dependency was never called. It is now.

Three analyses are available — `deal_review`, `seller_brief`, and
`portfolio_priorities` — each constrained to a JSON schema via
`output_config.format`, so callers consume typed fields rather than parsing
prose. Requests run on `claude-opus-5` with adaptive thinking and server-side
refusal fallback.

Two properties matter as much as the model call:

- **Never silently fabricated.** Without `ANTHROPIC_API_KEY`, each analysis falls
  back to a genuinely useful rule-based version labelled `source="deterministic"`
  with a `fallback_reason`. Model outages degrade analysis quality; they never
  take down the underwriting path.
- **Inside the safety boundary.** The system prompt encodes the same approval
  gates as the rest of the system: the model may research, score, draft, and
  recommend, but never assert funding status, title status, authority to sell,
  or that a document is binding.

Configuration: `CLAUDE_MODEL`, `CLAUDE_EFFORT`, `CLAUDE_SERVER_SIDE_FALLBACK`.

## Adaptive lead scoring

`fable5-plan.yaml` ends its workflow with `update_learning_records`, but nothing
ever fed outcomes back into the scoring weights. This engine closes that loop: an
L2-regularised logistic regression fit on resolved deals, returning a genuine
conversion probability.

- **Shrinkage to the prior.** With little history, scoring returns the legacy
  weighting anchored to the observed base rate. The fitted model's share is
  `n / (n + 40)`, so there is no regime cliff and three data points never
  overrule the prior.
- **Attribution.** Every score decomposes into per-feature log-odds
  contributions.
- **Honest calibration.** Brier score, log loss, and AUC are reported and
  explicitly marked in-sample.
- **Relative banding.** A 10% lead is a priority in a 2% market and a
  deprioritisation in a 40% one, so bands are multiples of the base rate.

Open deals are excluded from training — labelling them zero would teach the model
to predict "has not closed yet" rather than "will not close".

## Buyer intelligence

Response probability combines buy-box fit, engagement, reliability, price fit,
and verified funds. Engagement decays with a ~120-day half-life, which is the
distinction the flat `response_rate` field could not make: a buyer who answered
ten times last year and has ignored the desk since no longer scores like one who
answered yesterday.

`optimize_assignments` then solves the *portfolio* problem. Ranking each deal
independently sends every deal to the same few top buyers, so the best buyers get
spammed and the rest of the list goes unused. A greedy pass plus 2-opt swap
improvement maximises expected revenue under a per-buyer contact capacity. The
response reports both the capacity-constrained revenue and the unconstrained
figure — the latter is an upper bound, not a target.

Plans are proposals: launching one to buyers still requires an approved campaign
through the existing approval gate.

## Pipeline forecasting

Stage transition rates are estimated with a Beta prior, so a stage with two
observations does not report 100% or 0% conversion. Each open deal is discounted
by its chained probability of reaching close, and the aggregate carries an
interval from the variance of the underlying Bernoulli outcomes.

The forecast also reports `overstatement_vs_nominal` — the gap between the raw
fee sum the legacy brief reported and what the pipeline is actually worth — plus
stalled deals and a bottleneck ranking that weights value held by dwell time and
inverse advance probability.

Two caveats are stated in every response: deals are treated as independent (a
correlated market shock would widen the interval), and days-in-stage is measured
from last update, which is a lower bound on true dwell time.

## API surface

All routes are workspace-scoped through `WorkspaceEntity`.

| Route | Method | Role | Purpose |
|---|---|---|---|
| `/deal-intelligence/status` | GET | any | Engine availability, scoring-model state, and data gaps |
| `/deal-intelligence/market/{zip}` | GET | any | Census ACS context and FHFA appreciation for a ZIP |
| `/deal-intelligence/underwrite` | POST | acquisitions | Comps → ARV → repairs → simulated offer |
| `/deal-intelligence/leads/ranked` | GET | any | Leads ranked by calibrated conversion probability |
| `/deal-intelligence/leads/{id}/call-brief` | GET | acquisitions | Structured acquisitions call brief |
| `/deal-intelligence/forecast` | GET | any | Probability-weighted revenue forecast |
| `/deal-intelligence/disposition/plan` | POST | disposition | Portfolio buyer assignment |
| `/deal-intelligence/briefing` | GET | any | Combined executive briefing |

The operations console renders the briefing at `/owner/deal-intelligence`.

The legacy `POST /underwrite` endpoint keeps its original fields and gains a
`risk_adjusted` block carrying the simulation, so existing consumers are
unaffected.

## Testing

`backend/tests/` covers each engine's behaviour and invariants — adjustment
directions, outlier rejection, confidence widening under disagreement, model
recovery of true drivers, capacity constraints, monotonic percentiles — plus
end-to-end API tests that assert workspace isolation.

Note that `tests/conftest.py` creates the schema for the test database. Runtime
schema creation remains prohibited in `backend/app/` and `backend/api/`, and
`test_production_hardening` still enforces that.

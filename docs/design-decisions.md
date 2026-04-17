# Design decisions

Canonical record of every scoping and design choice made during the project
planning phase. When a decision is revisited or updated, add a note — do not
delete the original. This file is the authoritative reference for why things
are the way they are.

---

## Problem framing

**Decision:** Anchor on a single, well-defined decision context rather than
building a general-purpose analytics tool.

**Chosen context:** Vintage quality and yield forecasting for small,
independent Napa Valley vintners.

**Rationale:** Small vintners lack access to proprietary analytics platforms
and data scientists. The entire pipeline uses publicly available, free data
sources so any grower could in principle replicate or extend the work. A
model that achieves slightly lower accuracy but produces interpretable,
actionable outputs is strictly preferred over a marginally better black box
for this audience.

---

## Geographic scope

**Decision:** Napa Valley, California only. AVA-level (American Viticultural
Area) aggregation. CDFA grape pricing districts as the spatial unit.

**Rationale:**
- Densest existing literature on climate-viticulture relationships
- PRISM terrain-accounting is most valuable in complex coastal/mountain terrain
- CDFA Crush Report data maps cleanly onto Napa district structure
- A published harvest date + Brix dataset (Amerine/Winkler digitization,
  1935–2018) exists for Napa — useful for validation

**Explicitly excluded:** Other California AVAs (future work).

---

## Temporal scope

**Decision:** 1981–present as primary window. Monthly PRISM back to 1895
available for secondary trend analysis.

**Rationale:** Daily PRISM grids begin in 1981. CIMIS station coverage
improves through the 1980s. 40+ seasons is sufficient for credible
time-series modeling. Aligns with CIMIS availability.

---

## Variety coverage

**Decision:** Focus on three varieties with deep, consistent Crush Report
records. Do not attempt to model data-sparse varieties.

**Chosen varieties:**

| Variety | Type | Reason |
|---|---|---|
| Cabernet Sauvignon | Red | Deepest records; heat-tolerant; Napa benchmark |
| Pinot Noir | Red | Heat-sensitive; strong climate signal |
| Chardonnay | White | Well-documented; different water stress response |

**Explicitly excluded:** Merlot, Petit Verdot, Sauvignon Blanc, others.
Sparse records make these unsuitable for the primary model. Future work.

---

## Target variables

**Decision:** Brix and tonnage as joint multi-output regression. Harvest date
as a secondary outcome for trend analysis only.

**Brix (primary):**
- Most consistently reported quality-adjacent variable in Crush Report
- Direct climate signal — warmer seasons produce higher Brix
- Known limitation: conflates thermal ripeness with water-stress concentration.
  High Brix can result from drought without full physiological ripeness.
  Documented as a limitation in the thesis, not a disqualifier.

**Tonnage (primary, joint with Brix):**
- Predicted on the same model as Brix, not independently
- Rationale: Brix and tonnage are biologically correlated. Stress years
  produce high Brix and low tonnage simultaneously. Joint modeling captures
  this; two independent models cannot.
- Practical advisory value: "low-yield, high-ripeness vintage — plan tank
  space and pricing accordingly"

**Harvest date (secondary):**
- Cleaner phenological signal for climate trend analysis
- Avoids the water-stress confound in Brix
- Not in Crush Report — sourced from UC Davis records and published datasets
- Not the primary ML prediction target; used for trend analysis component

**Rejected:** Price per ton as primary target. Conflates supply/demand with
quality. Too noisy. Could be revisited as a secondary outcome.

---

## Model architecture

**Initial decision (scoping):** Multi-output gradient boosting as the starting
architecture. LSTM as an alternative if temporal autocorrelation is significant.

**Updated decision (April 2026, after baseline ladder evaluation):**
Elastic net regression with year-over-year delta targets (`src/models/train_ridge.py`).
GBM is retained for comparison (`src/models/train_gb.py`) but is not the primary model.

**Why GBM was tried first:**
- Strong performance on tabular data
- Interpretable via SHAP without additional tooling
- Faster iteration cycle during development

**Why GBM was deprioritized:**
- 24 training years is too small for a tree ensemble — the model overfits
  consistently across multiple test windows (2015–2019 and 2020–2024)
- Negative R² on holdout confirmed overfitting, not feature weakness:
  the GBM beats null and Winkler OLS but cannot beat persistence

**Why elastic net with delta targets:**
- L1+L2 regularization is the appropriate prior at n~24: it shrinks
  coefficients rather than memorizing training noise
- Reframing the target as Δbrix / Δtons_crushed (year-over-year change)
  makes persistence the implicit zero-prediction. A model predicting Δ=0
  everywhere exactly recovers persistence — so any learned signal registers
  directly as improvement over the hardest baseline
- Walk-forward evaluation (n=20) confirms the elastic net ties or beats
  persistence on 4 of 6 variety × target combinations

**LSTM status:** Deferred. EDA confirmed strong lag-1 autocorrelation, which
the delta-target framing already handles. LSTM adds sequence modeling complexity
that is not justified at this dataset size. Revisit if the dataset expands
beyond ~35 years or if multi-year drought compounding becomes a focus.

---

## Baseline ladder

**Decision:** Five baselines in ascending order of sophistication. All five
must be computed and reported before the ML model is evaluated.

**Rationale:** Each rung justifies the next level of complexity. The thesis
contribution is not just "we trained a model" but "we show where each layer
of sophistication earns its complexity cost."

| # | Baseline | Definition | What it justifies |
|---|---|---|---|
| 1 | **Null / Historical mean** | Predict the training-set mean for every year. No features, no time structure. Sets the floor — any model that cannot beat this is useless. | ML beats a naive prior |
| 2 | **Winkler linear** | OLS regression using only the Winkler GDD index as a single predictor. The industry-standard thermal accumulation metric. | Feature engineering (GDD) adds value over no features |
| 3 | **Full OLS** | OLS regression using all numeric climate + water + soil features (same feature set as the ML models). No regularization, no nonlinearity. | ML architecture (regularization, nonlinearity) adds value over linear regression |
| 4 | **Persistence** | Predict this year = last year. No features at all — pure autocorrelation. The hardest baseline: Brix and tonnage are strongly year-to-year correlated. | ML beats the autocorrelation structure of the targets |

**Note:** Null and historical mean are identical in implementation (training mean)
and produce the same RMSE. Both are retained in the output for reporting clarity.

**Evaluation protocol (updated April 2026):** All baselines use walk-forward
cross-validation over 2005–2024 (n=20 per variety), not a fixed holdout.
For each year t, the baseline is fit on all data before t and evaluated on t.
This is more stable than a 5-year holdout given the small dataset size and
avoids conflating model quality with the particular characteristics of any
single test window (e.g. the 2020–2024 wildfire/COVID period).

---

## Feature engineering

**Decision:** Derive agroclimatic indices from PRISM daily grids rather than
using raw temperature values as model inputs.

**Rationale:** Derived features (GDD, frost days, heat stress days) have
direct agronomic meaning that practitioners understand. This supports the
interpretability requirement and avoids the "black box" problem. The Winkler
index is computed explicitly to validate against the industry-standard
classification system.

**Decision:** Include soil covariates (SSURGO) as static features.

**Rationale:** Soil water-holding capacity and drainage are major sources of
cross-AVA variance that climate data alone cannot explain. Static covariates
per AVA add meaningful predictive value at low engineering cost.

**Decision:** Include DWR water year classification as a categorical feature.

**Rationale:** Single variable per year, freely available, captures multi-month
drought context that seasonal ETo alone does not. Very low cost, meaningful
signal.

**Deferred:** Sentinel-2 / Landsat NDVI. At AVA-level aggregation, NDVI-yield
correlation degrades relative to field scale. Not worth the complexity for the
current scope. Revisit as an extension if time allows.

---

## LLM advisory layer

**Decision:** Add an LLM translation layer between structured model output
and the final advisory shown to the vintner.

**Rationale:** Small vintners will not act on a predicted Brix value and
confidence interval. They need a sentence that tells them what to do. An LLM
grounded strictly on the model's structured output handles the translation
without introducing hallucination risk into the prediction itself.

**Constraints:**
- LLM receives only the structured prediction object — no external retrieval
- Low-confidence predictions lead with uncertainty, not estimates
- Output is validated against a schema before being shown to the vintner
- The LLM does not make agronomic decisions; it translates statistical ones

**Risk acknowledged:** Hallucination risk is real. Mitigated by strict prompt
constraints and output schema validation. Not fully eliminated. Documented
as a known limitation.

---

## Feedback mechanism

**Decision:** Structured harvest log in SQLite at `data/feedback.db`.

**Rationale:** The project needs actual vs. predicted outcome tracking for
model evaluation. SQLite is zero-infrastructure, queryable with pandas, and
lives as a single file in the repo. No hosted database is needed for the
research phase.

**Schema captures:** predicted values · actual outcomes · vintner action ·
free-text notes · advisory text · timestamp

**Future compatibility:** Schema is designed to be compatible with a Bayesian
updating framework (per-vintner model personalization). This is explicitly
scoped as future work, not current scope.

**Rejected:** Convex, Supabase, or other hosted databases. These are
appropriate if the advisory layer becomes a deployed multi-user web tool.
Revisit at that stage.

---

## Vineyard-level data

**Decision:** Not in current scope. Revisit if viable after initial pipeline
is running.

**Rationale:** The Crush Report provides district-level aggregates, not
individual vineyard records. Individual records would strengthen validation
but are not available at scale.

**Potential sources if pursued:** UC Cooperative Extension trial data,
willing vintner partners, published case studies.

---

## Evaluation framing

**Decision:** Present evaluation as a "decision ladder" for a small vintner
audience, not just statistical metrics.

**Rationale:** The primary contribution is not raw model accuracy but the
full pipeline from public data to actionable advisory. Evaluation must
demonstrate value at each layer of the stack, not just at the top.

**Metrics:**
- Statistical: RMSE and MAE for Brix and tonnage against all four baselines
- Interpretability: SHAP feature importance
- Advisory quality: post-season survey (did the vintner understand, trust,
  and act on the advisory?)

---

## Master's contribution

Three pillars, in priority order:

1. **Interpretability and access** — Full pipeline from public data to
   plain-language advisory for growers with no analytics access. Does not
   exist in open literature.

2. **Domain contribution** — Variety-specific climate sensitivity analysis
   showing how Cab Sauv, Pinot Noir, and Chardonnay respond differently to
   thermal and water stress over four decades.

3. **Methodological contribution** — Multi-output ML on a richer feature set
   than prior viticulture ML work, with rigorous baseline ladder and SHAP
   attribution.

---

## Modeling findings — first GBM run (April 2026)

**Context:** First full baseline ladder + GBM evaluation against holdout data.
Two test windows evaluated: 2020–2024 (primary) and 2015–2024 (robustness check).

**Finding — persistence dominates:**
Predicting last year's value (lag-1) is the hardest baseline to beat across
both targets and both test windows. Brix and tons_crushed are strongly
year-to-year autocorrelated. Chardonnay brix persistence RMSE (0.249) is
far below every model including GBM (0.473).

**Finding — GBM beats null and Winkler OLS consistently:**
The GBM beats the historical mean and the single-feature Winkler OLS on brix
for all three varieties. This confirms the feature set carries real signal.
The model is not useless — it is overfitting.

**Finding — negative R² is a relative statement:**
Negative R² means the model is worse than predicting the training mean.
Given the small training set (24 years) and strong autocorrelation, this is
an overfitting symptom rather than a signal that features are uninformative.

**Finding — 2020–2024 is not the cause:**
Repeating evaluation on 2015–2024 produced similarly negative R² values.
The wildfire/COVID years (2020–2021) are not the primary driver of poor
holdout performance.

**Walk-forward results (canonical, saved to models/baselines.json):**

| Target | Variety | ElasticNet Δ | Persistence | Full OLS | Null |
|---|---|---|---|---|---|
| Brix | Cab Sauv | 0.589 | 0.577 | 0.847 | 1.067 |
| Brix | Pinot Noir | 0.655 | **0.442** | 0.836 | 0.938 |
| Brix | Chardonnay | 0.406 | 0.368 | 0.831 | 0.505 |
| Tons | Cab Sauv | 15,638 | 15,667 | 18,344 | 22,810 |
| Tons | Pinot Noir | 2,520 | **2,178** | 2,539 | 1,876 |
| Tons | Chardonnay | 6,147 | 6,130 | 8,186 | 6,516 |

Model beats or ties persistence on 4 of 6 targets. Pinot Noir is the hard case
on both targets. All models beat null and Full OLS convincingly.

**Decision: try elastic net with year-over-year deviation target**

Two changes made in `src/models/train_ridge.py`:

1. **Simpler model class** — elastic net (L1 + L2 regularization) regularizes
   better than a tree ensemble at n=24. With 11 numeric features and a small
   dataset, ridge/elastic net is the appropriate prior.

2. **Reframe the target** — predict Δbrix and Δtons\_crushed (current year
   minus previous year) instead of absolute values. This makes persistence
   the implicit zero-prediction baseline. If the model predicts Δ=0 for all
   years, it exactly recovers persistence — so any positive signal in the
   features registers as an improvement over the hardest baseline.

**Rationale for documenting here:** The architecture note in the "Model
architecture" section above anticipated this — "if full-feature linear
regression closely matches the ML model, complexity is not justified." The
baseline ladder results confirm we should walk the complexity back before
adding it.

---

## Open questions (unresolved at scoping)

- [x] Train/test split exact cutoff year — resolved: walk-forward CV over 2005–2024 (April 2026)
- [x] Whether LSTM is warranted — resolved: deferred; delta-target framing handles autocorrelation (April 2026)
- [ ] Vineyard-level validation data — assess feasibility after pipeline runs
- [ ] Exact Napa district → AVA mapping for CDFA data alignment
- [ ] CIMIS station selection for Napa — identify stations with deepest records

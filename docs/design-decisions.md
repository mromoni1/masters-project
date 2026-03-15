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

**Decision:** Multi-output gradient boosting as the starting architecture.
LSTM as an alternative if temporal autocorrelation is significant in EDA.

**Rationale for gradient boosting first:**
- Strong performance on tabular data
- Interpretable via SHAP without additional tooling
- Faster iteration cycle during development
- Multi-output extension (XGBoost, LightGBM) is straightforward

**Rationale for LSTM consideration:**
- Vineyard outcomes are temporally autocorrelated
- Consecutive drought years have compounding effects not captured by
  single-season features
- Only pursue if EDA shows significant lag correlations

**Architecture is not fixed** — the baseline ladder results will inform the
final choice. If full-feature linear regression closely matches the ML model,
complexity is not justified and the linear model should be used.

---

## Baseline ladder

**Decision:** Four baselines in ascending order of sophistication. All four
must be computed and reported before the ML model is evaluated.

**Rationale:** Each rung justifies the next level of complexity. The thesis
contribution is not just "we trained a model" but "we show where each layer
of sophistication earns its complexity cost."

| # | Baseline | What it justifies |
|---|---|---|
| 1 | Historical mean (10-yr avg) | ML beats naive prior |
| 2 | Winkler GDD linear | Feature engineering adds value |
| 3 | Full feature linear | ML architecture adds value |
| 4 | Persistence (last yr = this yr) | ML beats autocorrelation |

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

## Open questions (unresolved at scoping)

- [ ] Train/test split exact cutoff year — depends on data distribution in EDA
- [ ] Whether LSTM is warranted — depends on lag correlation analysis in EDA
- [ ] Vineyard-level validation data — assess feasibility after pipeline runs
- [ ] Exact Napa district → AVA mapping for CDFA data alignment
- [ ] CIMIS station selection for Napa — identify stations with deepest records

# Architecture

Reference for the full pipeline design. Describes every layer from raw data
ingestion to the LLM advisory output. Read this before touching any pipeline code.

---

## Pipeline overview

Five layers in sequence. Each layer has a single responsibility and a clean
handoff to the next.

| Layer | Input | Output |
|---|---|---|
| Data layer | Raw source downloads | Unmodified files in `data/raw/` |
| Feature layer | Raw data | Engineered features in `data/processed/` |
| Model layer | Feature matrix | Trained model artifacts in `models/` |
| Output layer | Model predictions | Structured prediction objects |
| Advisory layer | Structured predictions | Plain-language harvest advisories |

---

## Layer 1 — Data layer

Ingest only. No transformation happens here. Files land in `data/raw/` and
are never modified after download.

**Sources:**
- PRISM daily grids (tmin, tmax, tmean, ppt, vpdmin, vpdmax) — 1981–present
- CDFA Grape Crush Report CSVs — 40+ year archive
- CIMIS station data via API — ETo and weather variables
- SSURGO soil data — static download per AVA bounding box
- DWR water year classifications — annual categorical variable

**Conventions:**
- One subdirectory per source: `data/raw/prism/`, `data/raw/cdfa/`, etc.
- Raw files are read-only after download. Never edit in place.
- Download scripts live in `src/ingestion/`. Each source has its own script.

---

## Layer 2 — Feature layer

All transformation and feature engineering happens here. Input is `data/raw/`,
output is `data/processed/`.

**Derived agroclimatic indices (from PRISM daily grids):**

| Feature | Definition | Window |
|---|---|---|
| GDD | Growing degree days, base 10°C | Apr 1 – Oct 31 |
| Frost days | Days with tmin < 0°C | Mar 1 – May 31 |
| Heat stress days | Days with tmax > 35°C | Apr 1 – Oct 31 |
| Winkler index | Cumulative GDD sum | Apr 1 – Oct 31 |
| Precip total | Total precipitation | Oct 1 – Mar 31 (winter) |
| Tmax mean (veraison) | Mean daily max temp | Jul 1 – Aug 31 |

**Water features (from CIMIS):**

| Feature | Definition |
|---|---|
| Season ETo | Cumulative ETo, Apr 1 – Oct 31 |
| Drought class | DWR water year category (wet/normal/dry/critically dry) |

**Static covariates (from SSURGO, one value per AVA):**

| Feature | Type |
|---|---|
| Soil AWC | Continuous — available water capacity |
| Drainage class | Categorical |
| Clay fraction | Continuous |
| Variety | Categorical (Cab Sauv / Pinot Noir / Chardonnay) |
| AVA district | Categorical |

**Output format:** One row per (year × variety × AVA district). Stored as
Parquet in `data/processed/features.parquet`.

---

## Layer 3 — Model layer

Multi-output regression predicting Brix and tonnage jointly. Both targets are
predicted from the same feature matrix in a single model.

**Rationale for joint modeling:** Brix and tonnage are biologically correlated.
Stress years produce high Brix and low tonnage simultaneously. A joint model
captures this relationship; two independent models cannot.

**Architecture candidates:**
- Gradient boosting (XGBoost / LightGBM) — strong baseline, interpretable
  via SHAP, handles tabular data well, recommended starting point
- LSTM — appropriate if temporal autocorrelation proves significant in EDA;
  requires sequential input structure

**Baseline ladder (must be run before any ML model):**

| # | Baseline | Purpose |
|---|---|---|
| 1 | Historical mean (10-yr avg) | Minimum bar — beats the vintner's prior |
| 2 | Winkler GDD linear regression | Justifies feature engineering |
| 3 | Full feature linear regression | Isolates feature vs architecture contribution |
| 4 | Persistence (last year = this year) | Must be beaten to justify ML |

**Train/test split strategy:** Leave-last-N-years-out. Do not use random split
on time series data — this leaks future information into training.

**Artifacts saved to `models/`:**
- Trained model file (`.pkl` or `.pt`)
- SHAP explainer object
- Feature importance summary
- Evaluation metrics against all four baselines

---

## Layer 4 — Output layer

Converts raw model predictions into structured prediction objects before
passing to the advisory layer. Adds confidence framing.

**Structured prediction schema:**

```python
{
  "variety": str,           # "Cabernet Sauvignon"
  "ava_district": str,      # CDFA district name
  "season_year": int,       # e.g. 2024
  "brix_predicted": float,  # point estimate
  "brix_range": tuple,      # (lower, upper) confidence interval
  "tonnage_predicted": float,
  "tonnage_range": tuple,
  "harvest_window": str,    # e.g. "late September – early October"
  "confidence": str,        # "high" / "moderate" / "low"
  "confidence_note": str    # plain-language explanation of confidence level
}
```

**Confidence classification:**
- High: prediction falls within historical distribution, all key features
  present, season follows recognizable pattern
- Moderate: one or more features missing or imputed, season near distribution
  boundary
- Low: unusual season (e.g. late frost + heat spike + drought), model
  extrapolating — advisory must flag this explicitly

---

## Layer 5 — Advisory layer

LLM translation layer. Receives a structured prediction object and produces
a plain-language harvest advisory for a small vintner.

**Constraints (non-negotiable):**
- LLM receives only the structured prediction object as context
- No external knowledge retrieval, no web search, no freelance agronomic advice
- Output is grounded strictly in what the model predicted
- Low-confidence predictions must surface uncertainty language explicitly

**Input to LLM:** Structured prediction object + vineyard context
(variety, AVA, current season climate summary in plain text)

**Output format (target):**
> "Based on this season's growing conditions, your [Variety] block is trending
> toward [Brix estimate] Brix at harvest — [above/below/near] your 10-year
> average of [X]. Tonnage is projected [higher/lower/near average]. Given
> [key climate driver], consider beginning harvest checks around [date window].
> [Confidence caveat if applicable.]"

**Uncertainty handling:** If confidence is Low, the advisory leads with the
uncertainty before the estimate, not after. Never bury the caveat.

---

## Feedback mechanism

Structured harvest log capturing actual vs. predicted outcomes. Lives in
SQLite at `data/feedback.db`. See `docs/database.md` for schema.

**Purpose:** Model evaluation, future Bayesian updating, advisory quality
assessment.

**Fields:** predicted values · actual outcomes · vintner action taken ·
free-text notes · advisory text shown · timestamp

---

## Evaluation strategy

Report metrics against all four baselines for both targets:
- RMSE and MAE for Brix predictions
- RMSE and MAE for tonnage predictions
- SHAP feature importance — which features drive predictions most
- Advisory quality — post-season survey: did the vintner understand, trust,
  and act on the advisory?

Present results as a "decision ladder" — each layer of complexity is
justified by the gain it provides relative to added cost.

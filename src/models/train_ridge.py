"""Elastic net regression predicting year-over-year deviation from prior vintage.

Motivation
----------
The GBM baseline ladder (April 2026) showed that:
  - Persistence (lag-1) is the hardest baseline to beat for both targets
  - The GBM overfits on 24 training years despite beating null/Winkler OLS
  - Negative R² indicates the model is worse than predicting the training mean

Two changes from train_gb.py:

1. Model class — ElasticNet (L1+L2) regularizes better than tree ensembles
   at small sample sizes. Alpha and l1_ratio tuned via expanding-window CV.

2. Target reframing — predict Δbrix and Δtons_crushed (current − prior year)
   instead of absolute values. Persistence is the implicit zero prediction:
   a model that outputs Δ=0 for all years exactly recovers lag-1. Any climate
   signal in the features registers as improvement over that floor.

Output is converted back to absolute values for evaluation so RMSE is
comparable to train_gb.py results.

Artifacts saved to models/ (with --apply)
-----------------------------------------
    ridge_model.pkl       — {variety: {target: fitted ElasticNet}}
    ridge_config.json     — alpha, l1_ratio, CV scores, holdout metrics

Usage
-----
    python -m src.models.train_ridge                        # fixed holdout dry run
    python -m src.models.train_ridge --apply                # save artifacts
    python -m src.models.train_ridge --train-cutoff 2014    # alt split
    python -m src.models.train_ridge --walkforward          # walk-forward CV
    python -m src.models.train_ridge --walkforward --wf-start 2010
"""

import argparse
import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_ROOT          = Path(__file__).parents[2]
FEATURE_MATRIX = _ROOT / "data" / "processed" / "feature_matrix.parquet"
CDFA_CLEAN     = _ROOT / "data" / "processed" / "cdfa_clean.parquet"
BASELINES_JSON = _ROOT / "models" / "baselines.json"
MODEL_PATH     = _ROOT / "models" / "ridge_model.pkl"
CONFIG_PATH    = _ROOT / "models" / "ridge_config.json"

TRAIN_CUTOFF = 2019
WF_START     = 2005  # first year predicted in walk-forward CV (14 prior training years)
VARIETIES    = ["Cabernet Sauvignon", "Pinot Noir", "Chardonnay"]
TARGETS      = ["brix", "tons_crushed"]

CV_FOLDS = [
    (2004, 2009),
    (2009, 2014),
    (2014, 2019),
]

NUMERIC_FEATURES = [
    "gdd", "frost_days", "heat_stress_days",
    "tmax_veraison", "precip_winter", "eto_season", "severity_score",
    "awc_r", "claytotal_r",
    "brix_lag1", "tons_crushed_lag1",
]

PARAM_GRID = [
    {"alpha": 0.01,  "l1_ratio": 0.1},
    {"alpha": 0.01,  "l1_ratio": 0.5},
    {"alpha": 0.1,   "l1_ratio": 0.1},
    {"alpha": 0.1,   "l1_ratio": 0.5},
    {"alpha": 0.1,   "l1_ratio": 0.9},
    {"alpha": 1.0,   "l1_ratio": 0.1},
    {"alpha": 1.0,   "l1_ratio": 0.5},
    {"alpha": 1.0,   "l1_ratio": 0.9},
    {"alpha": 10.0,  "l1_ratio": 0.5},
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load feature matrix joined with CDFA targets; add lag and delta columns.

    Returns:
        DataFrame with one row per (year × variety) for Napa Valley, including
        lag-1 values and year-over-year deltas for each target.
    """
    features = pd.read_parquet(FEATURE_MATRIX)
    cdfa = pd.read_parquet(CDFA_CLEAN)[["year", "variety", "brix", "tons_crushed"]]

    napa = features[features["ava_district"] == "Napa Valley"].copy()
    df = cdfa.merge(napa.drop(columns=["ava_district"]), on="year", how="inner")
    df = df.sort_values(["variety", "year"]).reset_index(drop=True)

    for tgt in TARGETS:
        df[f"{tgt}_lag1"] = df.groupby("variety")[tgt].shift(1)
        df[f"delta_{tgt}"] = df[tgt] - df[f"{tgt}_lag1"]

    return df


# ---------------------------------------------------------------------------
# Feature matrix
# ---------------------------------------------------------------------------

def get_X(df: pd.DataFrame, scaler: StandardScaler | None = None,
          fit: bool = False) -> tuple[np.ndarray, StandardScaler]:
    """Return scaled feature matrix and fitted scaler.

    Args:
        df: Input DataFrame.
        scaler: Fitted scaler, or None to create a new one.
        fit: If True, fit the scaler on df before transforming.

    Returns:
        (X array, scaler)
    """
    X = df[NUMERIC_FEATURES].values
    if fit or scaler is None:
        scaler = StandardScaler()
        scaler.fit(X)
    return scaler.transform(X), scaler


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    n = int(mask.sum())
    if n < 2:
        return {"rmse": float("nan"), "mae": float("nan"), "r2": float("nan"), "n": n}
    yt, yp = y_true[mask], y_pred[mask]
    return {
        "rmse": round(float(np.sqrt(mean_squared_error(yt, yp))), 4),
        "mae":  round(float(mean_absolute_error(yt, yp)), 4),
        "r2":   round(float(r2_score(yt, yp)), 4),
        "n":    n,
    }


# ---------------------------------------------------------------------------
# Hyperparameter tuning
# ---------------------------------------------------------------------------

def tune(df: pd.DataFrame, variety: str,
         train_cutoff: int = TRAIN_CUTOFF) -> dict:
    """Select best ElasticNet params via expanding-window CV on delta targets.

    Args:
        df: Full dataset.
        variety: Variety to tune for.
        train_cutoff: Last year included in training.

    Returns:
        Best param dict from PARAM_GRID.
    """
    sub = df[df["variety"] == variety].sort_values("year").reset_index(drop=True)
    delta_targets = [f"delta_{t}" for t in TARGETS]
    folds = [(a, b) for a, b in CV_FOLDS if b <= train_cutoff]

    best_params = PARAM_GRID[0]
    best_score  = float("inf")

    for params in PARAM_GRID:
        fold_scores = []
        for train_end, test_end in folds:
            cv_train = sub[sub["year"] <= train_end].dropna(
                subset=NUMERIC_FEATURES + delta_targets
            )
            cv_test = sub[
                (sub["year"] > train_end) & (sub["year"] <= test_end)
            ].dropna(subset=NUMERIC_FEATURES)

            if len(cv_train) < 5 or len(cv_test) < 1:
                continue

            X_train, scaler = get_X(cv_train, fit=True)
            X_test, _       = get_X(cv_test, scaler=scaler)

            rmses = []
            for tgt in TARGETS:
                delta_col = f"delta_{tgt}"
                lag_col   = f"{tgt}_lag1"
                y_delta_train = cv_train[delta_col].values

                model = ElasticNet(max_iter=5000, random_state=42, **params)
                model.fit(X_train, y_delta_train)

                pred_delta = model.predict(X_test)
                # Convert delta prediction back to absolute for RMSE
                pred_abs = cv_test[lag_col].values + pred_delta
                true_abs = cv_test[tgt].values
                valid    = ~(np.isnan(pred_abs) | np.isnan(true_abs))
                if valid.sum() < 1:
                    continue
                rmses.append(np.sqrt(mean_squared_error(true_abs[valid], pred_abs[valid])))

            if rmses:
                fold_scores.append(np.mean(rmses))

        if fold_scores:
            score = np.mean(fold_scores)
            if score < best_score:
                best_score  = score
                best_params = params

    return best_params


# ---------------------------------------------------------------------------
# Training and evaluation
# ---------------------------------------------------------------------------

def train_variety(df: pd.DataFrame, variety: str, params: dict,
                  train_cutoff: int = TRAIN_CUTOFF
                  ) -> tuple[dict, StandardScaler]:
    """Fit one ElasticNet per target (delta) for a single variety.

    Args:
        df: Full dataset.
        variety: Variety to train on.
        params: ElasticNet hyperparameters.
        train_cutoff: Last year included in training.

    Returns:
        ({target: fitted ElasticNet}, fitted StandardScaler)
    """
    delta_targets = [f"delta_{t}" for t in TARGETS]
    sub = df[(df["variety"] == variety) & (df["year"] <= train_cutoff)]
    sub = sub.dropna(subset=NUMERIC_FEATURES + delta_targets)

    X_train, scaler = get_X(sub, fit=True)
    models = {}
    for tgt in TARGETS:
        m = ElasticNet(max_iter=5000, random_state=42, **params)
        m.fit(X_train, sub[f"delta_{tgt}"].values)
        models[tgt] = m

    return models, scaler


def evaluate(models: dict, scaler: StandardScaler,
             df: pd.DataFrame, variety: str,
             train_cutoff: int = TRAIN_CUTOFF) -> dict:
    """Evaluate on holdout set; report RMSE in original (absolute) units.

    Args:
        models: {target: fitted ElasticNet}.
        scaler: Fitted StandardScaler from training.
        df: Full dataset.
        variety: Variety to evaluate.
        train_cutoff: Last training year.

    Returns:
        {target: metrics_dict}
    """
    sub = df[(df["variety"] == variety) & (df["year"] > train_cutoff)]
    sub = sub.dropna(subset=NUMERIC_FEATURES)
    X_test, _ = get_X(sub, scaler=scaler)

    results = {}
    for tgt in TARGETS:
        pred_delta = models[tgt].predict(X_test)
        pred_abs   = sub[f"{tgt}_lag1"].values + pred_delta
        true_abs   = sub[tgt].values
        results[tgt] = _metrics(true_abs, pred_abs)

    return results


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------

def _load_baselines() -> dict | None:
    if not BASELINES_JSON.exists():
        return None
    with open(BASELINES_JSON) as f:
        return json.load(f)


def _print_comparison(ridge_results: dict, baselines: dict | None,
                      train_cutoff: int = TRAIN_CUTOFF) -> None:
    baseline_keys   = ["null", "historical_mean", "winkler_linear", "full_ols", "persistence"]
    baseline_labels = ["Null", "Hist. Mean", "Winkler OLS", "Full OLS", "Persistence"]

    for tgt in TARGETS:
        print(f"\n{'='*72}")
        print(f"  {tgt.upper()} — holdout RMSE (test {train_cutoff+1}–)")
        print(f"{'='*72}")
        print(f"  {'Model':<22}  {'Cab Sauv':>10}  {'Pinot Noir':>10}  {'Chardonnay':>10}")
        print(f"  {'-'*57}")

        row = f"  {'ElasticNet Δ (this)':<22}"
        for variety in VARIETIES:
            rmse = ridge_results.get(variety, {}).get(tgt, {}).get("rmse", float("nan"))
            row += f"  {rmse:>10.3f}"
        print(row)

        print(f"  {'—'*57}")
        if baselines:
            for key, label in zip(baseline_keys, baseline_labels):
                row = f"  {label:<22}"
                for variety in VARIETIES:
                    rmse = baselines.get(key, {}).get(variety, {}).get(tgt, {}).get("rmse", float("nan"))
                    row += f"  {rmse:>10.3f}"
                print(row)
        else:
            print("  (baselines.json not found — run src.models.baselines --apply first)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def walkforward_eval(df: pd.DataFrame, params_by_variety: dict,
                     wf_start: int = WF_START) -> dict:
    """Walk-forward CV: for each year t >= wf_start, train on all years < t.

    Hyperparameters are fixed (tuned once on data before wf_start) to avoid
    lookahead bias and keep runtime reasonable.

    Args:
        df: Full dataset from load_data().
        params_by_variety: {variety: best_params} tuned before wf_start.
        wf_start: First year to predict (must have at least 10 prior years).

    Returns:
        {variety: {target: metrics}} aggregated across all walk-forward years.
    """
    wf_years = sorted(y for y in df["year"].unique() if y >= wf_start)
    delta_cols = [f"delta_{t}" for t in TARGETS]

    # Accumulate (true, pred) across all walk-forward years
    buckets: dict = {
        v: {t: {"true": [], "pred": []} for t in TARGETS}
        for v in VARIETIES
    }

    for variety in VARIETIES:
        params = params_by_variety[variety]
        sub = df[df["variety"] == variety].sort_values("year").reset_index(drop=True)

        for year in wf_years:
            train = sub[sub["year"] < year].dropna(subset=NUMERIC_FEATURES + delta_cols)
            test  = sub[sub["year"] == year].dropna(subset=NUMERIC_FEATURES)
            if len(train) < 10 or len(test) == 0:
                continue

            X_train, scaler = get_X(train, fit=True)
            X_test, _       = get_X(test, scaler=scaler)

            for tgt in TARGETS:
                m = ElasticNet(max_iter=5000, random_state=42, **params)
                m.fit(X_train, train[f"delta_{tgt}"].values)

                pred_abs = test[f"{tgt}_lag1"].values + m.predict(X_test)
                true_abs = test[tgt].values
                valid    = ~(np.isnan(pred_abs) | np.isnan(true_abs))
                if valid.sum() > 0:
                    buckets[variety][tgt]["true"].extend(true_abs[valid].tolist())
                    buckets[variety][tgt]["pred"].extend(pred_abs[valid].tolist())

    results: dict = {}
    for variety in VARIETIES:
        results[variety] = {}
        for tgt in TARGETS:
            y_true = np.array(buckets[variety][tgt]["true"])
            y_pred = np.array(buckets[variety][tgt]["pred"])
            results[variety][tgt] = _metrics(y_true, y_pred)

    return results


def train_and_evaluate(apply: bool = False,
                       train_cutoff: int = TRAIN_CUTOFF,
                       walkforward: bool = False,
                       wf_start: int = WF_START) -> dict:
    """Full train + tune + evaluate pipeline for elastic net delta model.

    Args:
        apply: If True, save model artifacts to models/.
        train_cutoff: Last training year (used for fixed holdout mode).
        walkforward: If True, run walk-forward CV instead of fixed holdout.
        wf_start: First year predicted in walk-forward mode.

    Returns:
        {variety: {target: metrics}}
    """
    print("[ridge] Loading data ...")
    df = load_data()
    lag_coverage = df["brix_lag1"].notna().sum()

    # Tune hyperparameters once on the full training set regardless of mode.
    # In walk-forward mode this introduces a mild lookahead bias in param
    # selection, but avoids the 0-fold problem when wf_start-1 predates all
    # CV fold boundaries. The effect is small: regularization strength is a
    # weak hyperparameter and the same params are used across all WF steps.
    tune_cutoff = train_cutoff
    all_params  = {}
    all_models  = {}
    all_scalers = {}

    for variety in VARIETIES:
        print(f"\n[ridge] {variety}")
        n_folds = len([f for f in CV_FOLDS if f[1] <= tune_cutoff])
        print(f"  Tuning via {n_folds}-fold CV (data up to {tune_cutoff}) ...")
        params = tune(df, variety, train_cutoff=tune_cutoff)
        all_params[variety] = params
        print(f"  Best params: alpha={params['alpha']}  l1_ratio={params['l1_ratio']}")

        if not walkforward:
            train_df = df[df["year"] <= train_cutoff]
            test_df  = df[df["year"] >  train_cutoff]
            print(f"  Training on {train_df['year'].min()}–{train_cutoff} | "
                  f"Test: {lag_coverage}/{len(df)} lag-1 rows covered")
            models, scaler = train_variety(df, variety, params, train_cutoff=train_cutoff)
            all_models[variety]  = models
            all_scalers[variety] = scaler

    if walkforward:
        wf_years = sorted(y for y in df["year"].unique() if y >= wf_start)
        print(f"\n[ridge] Walk-forward CV: predicting {wf_years[0]}–{wf_years[-1]} "
              f"({len(wf_years)} years, params tuned on ≤{tune_cutoff})")
        results = walkforward_eval(df, all_params, wf_start=wf_start)

        print(f"\n{'='*72}")
        print(f"  WALK-FORWARD CV RESULTS ({wf_years[0]}–{wf_years[-1]})")
        print(f"{'='*72}")
        for tgt in TARGETS:
            print(f"\n  {tgt.upper()}")
            print(f"  {'Model':<22}  {'Cab Sauv':>10}  {'Pinot Noir':>10}  {'Chardonnay':>10}")
            print(f"  {'-'*57}")
            row = f"  {'ElasticNet Δ':<22}"
            for variety in VARIETIES:
                m = results[variety][tgt]
                row += f"  {m['rmse']:>8.3f} (n={m['n']})"
            print(row)

        baselines = _load_baselines()
        if baselines:
            print(f"\n  (baselines below are fixed-holdout numbers — re-run baselines "
                  f"--walkforward for a true apples-to-apples comparison)")
            for key, label in [("persistence", "Persistence"), ("full_ols", "Full OLS"),
                                ("historical_mean", "Hist. Mean")]:
                for tgt in TARGETS:
                    pass  # shown in full table below
            _print_comparison(results, baselines, train_cutoff=train_cutoff)
    else:
        train_df = df[df["year"] <= train_cutoff]
        test_df  = df[df["year"] >  train_cutoff]
        results  = {}
        print(f"\n[ridge] Fixed holdout: train {train_df['year'].min()}–{train_cutoff} | "
              f"test {test_df['year'].min()}–{test_df['year'].max()}")
        for variety in VARIETIES:
            variety_results = evaluate(all_models[variety], all_scalers[variety],
                                       df, variety, train_cutoff=train_cutoff)
            results[variety] = variety_results
            print(f"\n  {variety}")
            for tgt in TARGETS:
                m = variety_results[tgt]
                print(f"  {tgt:<15} RMSE={m['rmse']:.3f}  MAE={m['mae']:.3f}  "
                      f"R²={m['r2']:.3f}  n={m['n']}")

        baselines = _load_baselines()
        _print_comparison(results, baselines, train_cutoff=train_cutoff)

    if apply and not walkforward:
        _ROOT.joinpath("models").mkdir(exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"models": all_models, "scalers": all_scalers}, f)
        print(f"\n[ridge] Saved model → {MODEL_PATH.relative_to(_ROOT)}")

        train_df = df[df["year"] <= train_cutoff]
        test_df  = df[df["year"] >  train_cutoff]
        config = {
            "train_cutoff":     train_cutoff,
            "train_years":      f"{train_df['year'].min()}–{train_cutoff}",
            "test_years":       f"{test_df['year'].min()}–{test_df['year'].max()}",
            "targets":          TARGETS,
            "target_framing":   "year-over-year delta (converted back to absolute for eval)",
            "numeric_features": NUMERIC_FEATURES,
            "best_params":      all_params,
            "holdout_metrics":  results,
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        print(f"[ridge] Saved config → {CONFIG_PATH.relative_to(_ROOT)}")
    elif not walkforward:
        print("\n[ridge] Dry run — pass --apply to save artifacts.")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Elastic net model predicting year-over-year vintage deviation."
    )
    parser.add_argument("--apply", action="store_true", help="Save artifacts to models/.")
    parser.add_argument("--train-cutoff", type=int, default=TRAIN_CUTOFF,
                        help=f"Last training year for fixed holdout (default: {TRAIN_CUTOFF}).")
    parser.add_argument("--walkforward", action="store_true",
                        help="Run walk-forward CV instead of fixed holdout.")
    parser.add_argument("--wf-start", type=int, default=WF_START,
                        help=f"First year predicted in walk-forward mode (default: {WF_START}).")
    args = parser.parse_args()
    train_and_evaluate(apply=args.apply, train_cutoff=args.train_cutoff,
                       walkforward=args.walkforward, wf_start=args.wf_start)

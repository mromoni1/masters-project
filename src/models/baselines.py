"""Baseline ladder for vintage prediction.

Implements five baselines in order of increasing complexity. Each baseline is
evaluated three ways:
  1. Time-series cross-validation (expanding window, 3 folds of 5 test years)
  2. Final holdout (train 1991–2019, test 2020–2024)
  3. In-sample fit on the full training set (to detect overfitting)

Results are written to models/baselines.json.

Baselines
---------
0. Null (test-mean)  — predict the test-set mean; sets the R²=0 floor
1. Historical mean   — 10-year rolling average per variety
2. Winkler linear    — OLS: target ~ winkler_index, variety-stratified
3. Full feature OLS  — OLS: target ~ all continuous features, variety-stratified
4. Persistence       — predict this year = last year's actual value

Cross-validation design
-----------------------
Expanding window; minimum 14 training years; 5-year test windows:
  Fold 1: train 1991–2004, test 2005–2009
  Fold 2: train 1991–2009, test 2010–2014
  Fold 3: train 1991–2014, test 2015–2019
  Final:  train 1991–2019, test 2020–2024  (held-out, not part of CV)

CV metrics are reported as mean ± std across the three folds.

Metrics
-------
RMSE, MAE, R² for each (baseline × target × variety) combination.

Usage
-----
    python -m src.models.baselines            # print table, no file write
    python -m src.models.baselines --apply    # write models/baselines.json
"""

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
FEATURE_MATRIX = _ROOT / "data" / "processed" / "feature_matrix.parquet"
CDFA_CLEAN     = _ROOT / "data" / "processed" / "cdfa_clean.parquet"
OUTPUT_PATH    = _ROOT / "models" / "baselines.json"

TRAIN_CUTOFF = 2019   # inclusive; final holdout test = 2020–2024
ROLLING_WINDOW = 10

VARIETIES = ["Cabernet Sauvignon", "Pinot Noir", "Chardonnay"]
TARGETS   = ["brix", "tons_crushed"]

CONTINUOUS_FEATURES = [
    "gdd", "winkler_index", "frost_days", "heat_stress_days",
    "tmax_veraison", "precip_winter", "eto_season", "severity_score",
]

# Expanding-window CV folds: (last train year, last test year)
CV_FOLDS = [
    (2004, 2009),
    (2009, 2014),
    (2014, 2019),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load and join CDFA targets with Napa Valley feature matrix row.

    Returns:
        DataFrame with one row per (year × variety), sorted by variety then year.
    """
    features = pd.read_parquet(FEATURE_MATRIX)
    napa = features[features["ava_district"] == "Napa Valley"].drop(
        columns=["ava_district", "drainagecl", "texcl", "stations_used",
                 "drought_class", "missing_days_growing", "data_quality_warn",
                 "eto_days", "awc_r", "claytotal_r"],
        errors="ignore",
    )
    cdfa = pd.read_parquet(CDFA_CLEAN)[["year", "variety", "brix", "tons_crushed"]]
    df = cdfa.merge(napa, on="year", how="inner")
    return df.sort_values(["variety", "year"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Compute RMSE, MAE, R² — NaN-safe."""
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


def cv_summary(fold_metrics: list[dict]) -> dict[str, float]:
    """Aggregate per-fold metric dicts into mean ± std."""
    result = {}
    for key in ("rmse", "mae", "r2"):
        vals = [m[key] for m in fold_metrics if not np.isnan(m[key])]
        result[f"{key}_mean"] = round(float(np.mean(vals)), 4) if vals else float("nan")
        result[f"{key}_std"]  = round(float(np.std(vals)),  4) if vals else float("nan")
    result["n_folds"] = len(fold_metrics)
    return result


# ---------------------------------------------------------------------------
# Baseline functions — each returns {variety: {target: {holdout, train, cv}}}
# ---------------------------------------------------------------------------

def _run_with_cv(
    predict_fn,       # callable(train_df, test_df, tgt) -> np.ndarray of predictions
    df: pd.DataFrame,
) -> dict:
    """Evaluate predict_fn under CV, holdout, and in-sample regimes.

    Args:
        predict_fn: Function(train_df, test_df, tgt) → predicted values array.
        df: Full dataset.

    Returns:
        {variety: {target: {holdout: metrics, train: metrics, cv: cv_summary}}}
    """
    results = {}
    for variety in VARIETIES:
        sub = df[df["variety"] == variety].sort_values("year").copy()
        var_results = {}

        for tgt in TARGETS:
            # CV folds
            fold_metrics_list = []
            for train_end, test_end in CV_FOLDS:
                test_start = train_end + 1
                cv_train = sub[sub["year"] <= train_end]
                cv_test  = sub[(sub["year"] >= test_start) & (sub["year"] <= test_end)]
                if len(cv_train) < 5 or len(cv_test) < 1:
                    continue
                try:
                    y_pred = predict_fn(cv_train, cv_test, tgt)
                    fold_metrics_list.append(metrics(cv_test[tgt].values, y_pred))
                except Exception:
                    pass

            # Final holdout
            holdout_train = sub[sub["year"] <= TRAIN_CUTOFF]
            holdout_test  = sub[sub["year"] >  TRAIN_CUTOFF]
            y_pred_holdout = predict_fn(holdout_train, holdout_test, tgt)
            holdout_m = metrics(holdout_test[tgt].values, y_pred_holdout)

            # In-sample (train fit)
            y_pred_train = predict_fn(holdout_train, holdout_train, tgt)
            train_m = metrics(holdout_train[tgt].values, y_pred_train)

            var_results[tgt] = {
                "holdout": holdout_m,
                "train":   train_m,
                "cv":      cv_summary(fold_metrics_list) if fold_metrics_list else {},
            }

        results[variety] = var_results
    return results


# ---------------------------------------------------------------------------
# Baseline 0: Null (predict test-set mean)
# ---------------------------------------------------------------------------

def baseline_null(df: pd.DataFrame) -> dict:
    """Predict the mean of the test set — sets the R²=0 floor.

    Note: uses the test-set mean (an oracle), so this is the theoretical
    floor only. A real deployment would use the train-set mean instead.
    """
    def predict(train, test, tgt):
        return np.full(len(test), test[tgt].mean())

    return _run_with_cv(predict, df)


# ---------------------------------------------------------------------------
# Baseline 1: Historical mean (10-year rolling)
# ---------------------------------------------------------------------------

def baseline_historical_mean(df: pd.DataFrame) -> dict:
    """Predict using the 10-year rolling mean as of the last train year."""
    def predict(train, test, tgt):
        rolling = train[tgt].rolling(window=ROLLING_WINDOW, min_periods=1).mean()
        return np.full(len(test), rolling.iloc[-1])

    return _run_with_cv(predict, df)


# ---------------------------------------------------------------------------
# Baseline 2: Winkler linear
# ---------------------------------------------------------------------------

def baseline_winkler_linear(df: pd.DataFrame) -> dict:
    """OLS: target ~ winkler_index, variety-stratified."""
    def predict(train, test, tgt):
        t = train.dropna(subset=["winkler_index", tgt])
        e = test.dropna(subset=["winkler_index"])
        if len(t) < 3 or len(e) == 0:
            return np.full(len(test), float("nan"))
        model = LinearRegression().fit(t[["winkler_index"]], t[tgt])
        # align predictions back to test index (some rows may have been dropped)
        preds = np.full(len(test), float("nan"))
        idx = test.index.get_indexer(e.index)
        preds[idx] = model.predict(e[["winkler_index"]])
        return preds

    results = _run_with_cv(predict, df)

    # Print slope coefficients for literature validation
    print("\n[Winkler linear] Brix ~ Winkler slope (train 1991–2019):")
    print(f"  {'Variety':<25} {'slope':>9}  {'intercept':>10}  {'train R²':>9}")
    print(f"  {'-'*58}")
    for variety in VARIETIES:
        sub   = df[df["variety"] == variety]
        train = sub[sub["year"] <= TRAIN_CUTOFF].dropna(subset=["winkler_index", "brix"])
        model = LinearRegression().fit(train[["winkler_index"]], train["brix"])
        tr2   = r2_score(train["brix"], model.predict(train[["winkler_index"]]))
        print(f"  {variety:<25} {model.coef_[0]:>9.5f}  {model.intercept_:>10.4f}  {tr2:>9.3f}")

    return results


# ---------------------------------------------------------------------------
# Baseline 3: Full feature OLS
# ---------------------------------------------------------------------------

def baseline_full_ols(df: pd.DataFrame) -> dict:
    """OLS on all continuous features, variety-stratified."""
    def predict(train, test, tgt):
        t = train.dropna(subset=CONTINUOUS_FEATURES + [tgt])
        e = test.dropna(subset=CONTINUOUS_FEATURES)
        if len(t) < len(CONTINUOUS_FEATURES) + 1 or len(e) == 0:
            return np.full(len(test), float("nan"))
        model = LinearRegression().fit(t[CONTINUOUS_FEATURES], t[tgt])
        preds = np.full(len(test), float("nan"))
        idx = test.index.get_indexer(e.index)
        preds[idx] = model.predict(e[CONTINUOUS_FEATURES])
        return preds

    return _run_with_cv(predict, df)


# ---------------------------------------------------------------------------
# Baseline 4: Persistence
# ---------------------------------------------------------------------------

def baseline_persistence(df: pd.DataFrame) -> dict:
    """Predict this year = last year's actual value."""
    def predict(train, test, tgt):
        # Build a year→value lookup from all actuals up to end of train
        all_actuals = pd.concat([train, test]).sort_values("year").drop_duplicates("year")
        prior = all_actuals.set_index("year")[tgt].shift(1).to_dict()
        preds = test["year"].map(prior).values.astype(float)
        return preds

    return _run_with_cv(predict, df)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_table(all_results: dict) -> None:
    """Print holdout, CV mean, and train metrics side-by-side."""
    baseline_keys    = ["null", "historical_mean", "winkler_linear", "full_ols", "persistence"]
    baseline_labels  = ["0. Null", "1. Hist. Mean", "2. Winkler OLS", "3. Full OLS", "4. Persistence"]

    short_names = {
        "Cabernet Sauvignon": "Cab Sauv",
        "Pinot Noir": "P. Noir",
        "Chardonnay": "Chard.",
    }

    for tgt in TARGETS:
        for variety in VARIETIES:
            n_test  = all_results["historical_mean"][variety][tgt]["holdout"]["n"]
            n_train = all_results["historical_mean"][variety][tgt]["train"]["n"]
            print(f"\n{'='*72}")
            print(f"  {tgt.upper()}  —  {variety}  "
                  f"(train n={n_train}, holdout n={n_test}, CV folds=3×5yr)")
            print(f"{'='*72}")
            print(f"  {'Baseline':<16}  {'— Holdout —':^22}  {'— CV mean±std —':^28}  {'— Train —':^22}")
            print(f"  {'':16}  {'RMSE':>6} {'MAE':>6} {'R²':>7}  "
                  f"{'RMSE':>8} {'MAE':>8} {'R²':>8}  "
                  f"{'RMSE':>6} {'MAE':>6} {'R²':>7}")
            print(f"  {'-'*70}")

            for key, label in zip(baseline_keys, baseline_labels):
                r = all_results[key][variety][tgt]
                h = r.get("holdout", {})
                cv = r.get("cv", {})
                tr = r.get("train", {})

                def fmt(v, w=6):
                    return f"{v:{w}.3f}" if isinstance(v, float) and not np.isnan(v) else f"{'nan':>{w}}"

                holdout_str = f"{fmt(h.get('rmse',float('nan')))} {fmt(h.get('mae',float('nan')))} {fmt(h.get('r2',float('nan')),7)}"
                cv_str = (
                    f"{fmt(cv.get('rmse_mean',float('nan')),8)}"
                    f"±{fmt(cv.get('rmse_std',float('nan')),5)}  "
                    f"{fmt(cv.get('r2_mean',float('nan')),8)}"
                ) if cv else f"{'n/a':>8}  {'n/a':>8}  {'n/a':>8}"
                train_str = f"{fmt(tr.get('rmse',float('nan')))} {fmt(tr.get('mae',float('nan')))} {fmt(tr.get('r2',float('nan')),7)}"

                print(f"  {label:<16}  {holdout_str}  {cv_str}  {train_str}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_baselines(apply: bool = False) -> dict:
    """Run all baselines and return results dict.

    Args:
        apply: If True, write results to models/baselines.json.
    """
    print("[baselines] Loading data ...")
    df = load_data()
    train_df = df[df["year"] <= TRAIN_CUTOFF]
    test_df  = df[df["year"] >  TRAIN_CUTOFF]
    print(f"[baselines] Train: {train_df['year'].nunique()} years "
          f"({train_df['year'].min()}–{train_df['year'].max()}) | "
          f"n={len(train_df)} rows")
    print(f"[baselines] Test : {test_df['year'].nunique()} years "
          f"({test_df['year'].min()}–{test_df['year'].max()}) | "
          f"n={len(test_df)} rows")
    print(f"[baselines] CV   : {len(CV_FOLDS)} expanding-window folds "
          f"({CV_FOLDS[0][0]+1}–{CV_FOLDS[-1][1]}, 5-year test windows)")

    print("\n[baselines] Baseline 0: Null ...")
    b0 = baseline_null(df)

    print("[baselines] Baseline 1: Historical mean ...")
    b1 = baseline_historical_mean(df)

    print("[baselines] Baseline 2: Winkler linear ...")
    b2 = baseline_winkler_linear(df)

    print("\n[baselines] Baseline 3: Full feature OLS ...")
    b3 = baseline_full_ols(df)

    print("[baselines] Baseline 4: Persistence ...")
    b4 = baseline_persistence(df)

    all_results = {
        "null":            b0,
        "historical_mean": b1,
        "winkler_linear":  b2,
        "full_ols":        b3,
        "persistence":     b4,
        "_meta": {
            "train_cutoff":          TRAIN_CUTOFF,
            "train_years":           f"{train_df['year'].min()}–{train_df['year'].max()}",
            "test_years":            f"{test_df['year'].min()}–{test_df['year'].max()}",
            "rolling_window":        ROLLING_WINDOW,
            "cv_folds":              [{"train_end": a, "test_end": b} for a, b in CV_FOLDS],
            "features_used_full_ols": CONTINUOUS_FEATURES,
        },
    }

    print_table(all_results)

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n[baselines] Wrote → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print(f"\n[baselines] Dry run — pass --apply to write models/baselines.json")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run baseline ladder for vintage prediction.")
    parser.add_argument("--apply", action="store_true", help="Write results to models/baselines.json.")
    args = parser.parse_args()
    run_baselines(apply=args.apply)

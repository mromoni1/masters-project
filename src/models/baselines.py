"""Compute holdout metrics for simple baseline models.

Establishes a comparison floor for the gradient boosting model.
Uses the same train/test split and data loading as train_gb.py.

Baselines
---------
    null            — predict the training-set mean (per variety × target)
    historical_mean — same as null (alias kept for train_gb comparison table)
    persistence     — predict last year's value (lag-1)
    winkler_linear  — OLS using winkler_index only
    full_ols        — OLS using all numeric climate + water + soil features

Output
------
    models/baselines.json

Usage
-----
    python -m src.models.baselines            # print results only
    python -m src.models.baselines --apply    # write baselines.json
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_ROOT          = Path(__file__).parents[2]
FEATURE_MATRIX = _ROOT / "data" / "processed" / "feature_matrix.parquet"
CDFA_CLEAN     = _ROOT / "data" / "processed" / "cdfa_clean.parquet"
OUTPUT_PATH    = _ROOT / "models" / "baselines.json"

TRAIN_CUTOFF = 2019
WF_START     = 2005
VARIETIES    = ["Cabernet Sauvignon", "Pinot Noir", "Chardonnay"]
TARGETS      = ["brix", "tons_crushed"]

NUMERIC_FEATURES = [
    "gdd", "frost_days", "heat_stress_days",
    "tmax_veraison", "precip_winter", "eto_season", "severity_score",
    "awc_r", "claytotal_r",
    "brix_lag1", "tons_crushed_lag1",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load and join feature matrix with CDFA targets; add lag-1 columns.

    Returns:
        DataFrame with one row per (year × variety) for Napa Valley AVA,
        including lag-1 brix, lag-1 tons_crushed, and all climate features.
    """
    features = pd.read_parquet(FEATURE_MATRIX)
    cdfa = pd.read_parquet(CDFA_CLEAN)[["year", "variety", "brix", "tons_crushed"]]

    napa = features[features["ava_district"] == "Napa Valley"].copy()
    df = cdfa.merge(napa.drop(columns=["ava_district"]), on="year", how="inner")
    df = df.sort_values(["variety", "year"]).reset_index(drop=True)

    for tgt in TARGETS:
        df[f"{tgt}_lag1"] = df.groupby("variety")[tgt].shift(1)

    return df


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
# Baseline implementations
# ---------------------------------------------------------------------------

def _null(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    return np.full(len(test), train[target].mean())


def _persistence(test: pd.DataFrame, target: str) -> np.ndarray:
    return test[f"{target}_lag1"].values


def _ols(train: pd.DataFrame, test: pd.DataFrame,
         target: str, features: list[str]) -> np.ndarray:
    sub_train = train.dropna(subset=features + [target])
    sub_test  = test.copy()

    if len(sub_train) < 3:
        return np.full(len(test), float("nan"))

    model = LinearRegression()
    model.fit(sub_train[features], sub_train[target])

    X_test = sub_test[features].copy()
    pred = np.where(
        X_test.isna().any(axis=1),
        float("nan"),
        model.predict(X_test.fillna(0)),
    )
    return pred


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def walkforward_baselines(df: pd.DataFrame,
                          wf_start: int = WF_START) -> dict:
    """Walk-forward CV for all baselines: train on <t, predict t.

    Args:
        df: Full dataset from load_data().
        wf_start: First year to predict.

    Returns:
        {baseline_name: {variety: {target: metrics}}}
    """
    wf_years = sorted(y for y in df["year"].unique() if y >= wf_start)

    buckets: dict = {
        name: {v: {t: {"true": [], "pred": []} for t in TARGETS} for v in VARIETIES}
        for name in ["null", "historical_mean", "persistence", "winkler_linear", "full_ols"]
    }

    for variety in VARIETIES:
        sub = df[df["variety"] == variety].sort_values("year").reset_index(drop=True)

        for year in wf_years:
            train = sub[sub["year"] < year]
            test  = sub[sub["year"] == year]
            if len(train) < 10 or len(test) == 0:
                continue

            for tgt in TARGETS:
                true_val = test[tgt].values
                lag_val  = test[f"{tgt}_lag1"].values

                preds = {
                    "null":            _null(train, test, tgt),
                    "historical_mean": _null(train, test, tgt),
                    "persistence":     _persistence(test, tgt),
                    "winkler_linear":  _ols(train, test, tgt, ["winkler_index"]),
                    "full_ols":        _ols(train, test, tgt, NUMERIC_FEATURES),
                }
                for name, pred in preds.items():
                    valid = ~(np.isnan(true_val) | np.isnan(pred))
                    if valid.sum() > 0:
                        buckets[name][variety][tgt]["true"].extend(true_val[valid].tolist())
                        buckets[name][variety][tgt]["pred"].extend(pred[valid].tolist())

    results: dict = {}
    for name in buckets:
        results[name] = {}
        for variety in VARIETIES:
            results[name][variety] = {}
            for tgt in TARGETS:
                y_true = np.array(buckets[name][variety][tgt]["true"])
                y_pred = np.array(buckets[name][variety][tgt]["pred"])
                results[name][variety][tgt] = _metrics(y_true, y_pred)

    return results


def compute_baselines(apply: bool = False, train_cutoff: int = TRAIN_CUTOFF,
                      walkforward: bool = False, wf_start: int = WF_START) -> dict:
    """Compute all baseline holdout metrics and optionally save to JSON.

    Args:
        apply: If True, write results to models/baselines.json.
        train_cutoff: Last training year; years after this form the test set.

    Returns:
        Nested dict {baseline_name: {variety: {target: metrics_dict}}}.
    """
    print("[baselines] Loading data ...")
    df = load_data()

    if walkforward:
        wf_years = sorted(y for y in df["year"].unique() if y >= wf_start)
        print(f"[baselines] Walk-forward CV: predicting {wf_years[0]}–{wf_years[-1]} "
              f"({len(wf_years)} years)")
        results = walkforward_baselines(df, wf_start=wf_start)

        for tgt in TARGETS:
            print(f"\n{'='*72}")
            print(f"  {tgt.upper()} — walk-forward RMSE ({wf_years[0]}–{wf_years[-1]})")
            print(f"{'='*72}")
            print(f"  {'Baseline':<20}  {'Cab Sauv':>10}  {'Pinot Noir':>10}  {'Chardonnay':>10}")
            print(f"  {'-'*55}")
            for name in results:
                row = f"  {name:<20}"
                for variety in VARIETIES:
                    m = results[name][variety][tgt]
                    row += f"  {m['rmse']:>8.3f}(n={m['n']})"
                print(row)
    else:
        train_df = df[df["year"] <= train_cutoff]
        test_df  = df[df["year"] >  train_cutoff]
        print(f"[baselines] Train: {train_df['year'].nunique()} years "
              f"({train_df['year'].min()}–{train_cutoff}) | "
              f"Test: {test_df['year'].nunique()} years "
              f"({test_df['year'].min()}–{test_df['year'].max()})")

        baseline_fns: dict[str, callable] = {
            "null":             lambda tr, te, tgt: _null(tr, te, tgt),
            "historical_mean":  lambda tr, te, tgt: _null(tr, te, tgt),
            "persistence":      lambda tr, te, tgt: _persistence(te, tgt),
            "winkler_linear":   lambda tr, te, tgt: _ols(tr, te, tgt, ["winkler_index"]),
            "full_ols":         lambda tr, te, tgt: _ols(tr, te, tgt, NUMERIC_FEATURES),
        }

        results: dict[str, dict] = {name: {} for name in baseline_fns}

        for variety in VARIETIES:
            tr = train_df[train_df["variety"] == variety]
            te = test_df[test_df["variety"] == variety]
            for name, fn in baseline_fns.items():
                results[name][variety] = {}
                for tgt in TARGETS:
                    y_pred = fn(tr, te, tgt)
                    y_true = te[tgt].values
                    results[name][variety][tgt] = _metrics(y_true, y_pred)

        for tgt in TARGETS:
            print(f"\n{'='*72}")
            print(f"  {tgt.upper()} — holdout RMSE (test {train_cutoff+1}–{test_df['year'].max()})")
            print(f"{'='*72}")
            print(f"  {'Baseline':<20}  {'Cab Sauv':>10}  {'Pinot Noir':>10}  {'Chardonnay':>10}")
            print(f"  {'-'*55}")
            for name in baseline_fns:
                row = f"  {name:<20}"
                for variety in VARIETIES:
                    rmse = results[name][variety][tgt]["rmse"]
                    row += f"  {rmse:>10.3f}"
                print(row)

    if apply:
        OUTPUT_PATH.parent.mkdir(exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n[baselines] Wrote → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print("\n[baselines] Dry run — pass --apply to write baselines.json.")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute baseline holdout metrics.")
    parser.add_argument("--apply", action="store_true", help="Write models/baselines.json.")
    parser.add_argument("--train-cutoff", type=int, default=TRAIN_CUTOFF,
                        help=f"Last training year (default: {TRAIN_CUTOFF}).")
    parser.add_argument("--walkforward", action="store_true",
                        help="Run walk-forward CV instead of fixed holdout.")
    parser.add_argument("--wf-start", type=int, default=WF_START,
                        help=f"First year predicted in walk-forward mode (default: {WF_START}).")
    args = parser.parse_args()
    compute_baselines(apply=args.apply, train_cutoff=args.train_cutoff,
                      walkforward=args.walkforward, wf_start=args.wf_start)

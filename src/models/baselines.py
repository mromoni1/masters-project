"""Baseline ladder for vintage prediction.

Implements four baselines in order of increasing complexity. Each baseline is
evaluated on the same train/test split used for the ML model (cutoff: 2019).
Results are written to models/baselines.json.

Baselines
---------
1. Historical mean   — 10-year rolling average of brix and tons_crushed per variety
2. Winkler linear    — OLS: target ~ winkler_index, variety-stratified
3. Full feature OLS  — OLS: target ~ all continuous features, variety-stratified
4. Persistence       — predict this year = last year's actual value

Metrics
-------
RMSE, MAE, R² on the test set for each (baseline × target × variety) combination.

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

TRAIN_CUTOFF = 2019   # inclusive; test = 2020–2024 (from #36 EDA)
ROLLING_WINDOW = 10

VARIETIES = ["Cabernet Sauvignon", "Pinot Noir", "Chardonnay"]
TARGETS   = ["brix", "tons_crushed"]

CONTINUOUS_FEATURES = [
    "gdd", "winkler_index", "frost_days", "heat_stress_days",
    "tmax_veraison", "precip_winter", "eto_season", "severity_score",
]


# ---------------------------------------------------------------------------
# Data loading and preparation
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load and join CDFA targets with Napa Valley feature matrix row.

    Returns:
        DataFrame with one row per (year × variety), sorted by variety then year.
        Contains all continuous features plus brix and tons_crushed.
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


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train, test) split at TRAIN_CUTOFF."""
    return df[df["year"] <= TRAIN_CUTOFF].copy(), df[df["year"] > TRAIN_CUTOFF].copy()


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------

def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Compute RMSE, MAE, R² — return NaN-safe dict."""
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    if mask.sum() < 2:
        return {"rmse": float("nan"), "mae": float("nan"), "r2": float("nan")}
    yt, yp = y_true[mask], y_pred[mask]
    return {
        "rmse": round(float(np.sqrt(mean_squared_error(yt, yp))), 4),
        "mae":  round(float(mean_absolute_error(yt, yp)), 4),
        "r2":   round(float(r2_score(yt, yp)), 4),
    }


# ---------------------------------------------------------------------------
# Baseline 1: Historical mean (10-year rolling)
# ---------------------------------------------------------------------------

def baseline_historical_mean(df: pd.DataFrame) -> dict:
    """Predict each test year using the 10-year rolling mean of train years.

    For each variety, compute the rolling mean over the 10 years prior to the
    prediction year (using only years ≤ TRAIN_CUTOFF as the look-back window).
    Test predictions use the rolling mean as of TRAIN_CUTOFF.

    Returns:
        Nested dict: {variety: {target: metrics_dict}}
    """
    results = {}
    for variety in VARIETIES:
        sub = df[df["variety"] == variety].sort_values("year")
        train = sub[sub["year"] <= TRAIN_CUTOFF]
        test  = sub[sub["year"] >  TRAIN_CUTOFF]

        var_results = {}
        for tgt in TARGETS:
            # Rolling mean on train; last window value is the prediction for all test years
            rolling = train[tgt].rolling(window=ROLLING_WINDOW, min_periods=1).mean()
            pred_value = rolling.iloc[-1]
            y_pred = np.full(len(test), pred_value)
            y_true = test[tgt].values
            var_results[tgt] = metrics(y_true, y_pred)

        results[variety] = var_results
    return results


# ---------------------------------------------------------------------------
# Baseline 2: Winkler linear
# ---------------------------------------------------------------------------

def baseline_winkler_linear(df: pd.DataFrame) -> dict:
    """OLS regression: target ~ winkler_index, fit on train, evaluated on test.

    Variety-stratified. Also prints Winkler slope coefficients for validation
    against published Napa Valley literature ranges.

    Returns:
        Nested dict: {variety: {target: metrics_dict}}
    """
    results = {}
    print("\n[Winkler linear] Slope coefficients (Brix ~ Winkler Index):")
    print(f"  {'Variety':<25} {'slope':>8}  {'intercept':>10}  {'train R²':>9}")
    print(f"  {'-'*60}")

    for variety in VARIETIES:
        sub   = df[df["variety"] == variety].sort_values("year")
        train = sub[sub["year"] <= TRAIN_CUTOFF].dropna(subset=["winkler_index"])
        test  = sub[sub["year"] >  TRAIN_CUTOFF].dropna(subset=["winkler_index"])

        var_results = {}
        for tgt in TARGETS:
            X_train = train[["winkler_index"]].values
            y_train = train[tgt].values
            X_test  = test[["winkler_index"]].values
            y_true  = test[tgt].values

            model = LinearRegression().fit(X_train, y_train)
            y_pred = model.predict(X_test)
            var_results[tgt] = metrics(y_true, y_pred)

            if tgt == "brix":
                train_r2 = r2_score(y_train, model.predict(X_train))
                print(f"  {variety:<25} {model.coef_[0]:>8.5f}  {model.intercept_:>10.4f}  {train_r2:>9.3f}")

        results[variety] = var_results
    return results


# ---------------------------------------------------------------------------
# Baseline 3: Full feature OLS
# ---------------------------------------------------------------------------

def baseline_full_ols(df: pd.DataFrame) -> dict:
    """OLS on all continuous features, variety-stratified.

    Drops rows with any NaN in the feature set before fitting.

    Returns:
        Nested dict: {variety: {target: metrics_dict}}
    """
    results = {}
    for variety in VARIETIES:
        sub   = df[df["variety"] == variety].sort_values("year")
        train = sub[sub["year"] <= TRAIN_CUTOFF].dropna(subset=CONTINUOUS_FEATURES)
        test  = sub[sub["year"] >  TRAIN_CUTOFF].dropna(subset=CONTINUOUS_FEATURES)

        var_results = {}
        for tgt in TARGETS:
            X_train = train[CONTINUOUS_FEATURES].values
            y_train = train[tgt].values
            X_test  = test[CONTINUOUS_FEATURES].values
            y_true  = test[tgt].values

            model = LinearRegression().fit(X_train, y_train)
            y_pred = model.predict(X_test)
            var_results[tgt] = metrics(y_true, y_pred)

        results[variety] = var_results
    return results


# ---------------------------------------------------------------------------
# Baseline 4: Persistence
# ---------------------------------------------------------------------------

def baseline_persistence(df: pd.DataFrame) -> dict:
    """Predict this year = last year's actual value.

    For each test year, uses the most recent available actual (the prior year
    in the same variety). Years where the prior value is missing are excluded.

    Returns:
        Nested dict: {variety: {target: metrics_dict}}
    """
    results = {}
    for variety in VARIETIES:
        sub = df[df["variety"] == variety].sort_values("year").copy()
        for tgt in TARGETS:
            sub[f"{tgt}_lag1"] = sub[tgt].shift(1)

        test = sub[sub["year"] > TRAIN_CUTOFF]

        var_results = {}
        for tgt in TARGETS:
            valid = test[[tgt, f"{tgt}_lag1"]].dropna()
            y_true = valid[tgt].values
            y_pred = valid[f"{tgt}_lag1"].values
            var_results[tgt] = metrics(y_true, y_pred)

        results[variety] = var_results
    return results


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def print_table(all_results: dict) -> None:
    """Print a formatted comparison table of all baseline metrics."""
    baselines = ["historical_mean", "winkler_linear", "full_ols", "persistence"]
    labels    = ["1. Hist. Mean", "2. Winkler OLS", "3. Full OLS", "4. Persistence"]

    for tgt in TARGETS:
        print(f"\n{'='*80}")
        print(f"  Target: {tgt}")
        print(f"{'='*80}")
        header = f"  {'Baseline':<18}"
        for variety in VARIETIES:
            short = variety.replace("Cabernet Sauvignon", "Cab Sauv").replace("Pinot Noir", "P. Noir").replace("Chardonnay", "Chard.")
            header += f"  {short:^21}"
        print(header)
        subheader = f"  {'':18}"
        for _ in VARIETIES:
            subheader += f"  {'RMSE':>6} {'MAE':>6} {'R²':>6}  "
        print(subheader)
        print(f"  {'-'*78}")

        for name, label in zip(baselines, labels):
            row = f"  {label:<18}"
            for variety in VARIETIES:
                m = all_results[name][variety][tgt]
                rmse = f"{m['rmse']:.3f}" if not np.isnan(m['rmse']) else "  nan"
                mae  = f"{m['mae']:.3f}"  if not np.isnan(m['mae'])  else "  nan"
                r2   = f"{m['r2']:.3f}"   if not np.isnan(m['r2'])   else "  nan"
                row += f"  {rmse:>6} {mae:>6} {r2:>6}  "
            print(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_baselines(apply: bool = False) -> dict:
    """Run all four baselines and return the full results dict.

    Args:
        apply: If True, write results to models/baselines.json.

    Returns:
        Dict with keys: historical_mean, winkler_linear, full_ols, persistence.
        Each maps to {variety: {target: {rmse, mae, r2}}}.
    """
    print(f"[baselines] Loading data ...")
    df = load_data()
    train, test = split(df)
    print(f"[baselines] Train: {train['year'].nunique()} years ({train['year'].min()}–{train['year'].max()})")
    print(f"[baselines] Test : {test['year'].nunique()} years ({test['year'].min()}–{test['year'].max()})")
    print(f"[baselines] Varieties: {VARIETIES}")

    print("\n[baselines] Running baseline 1: Historical mean ...")
    b1 = baseline_historical_mean(df)

    print("[baselines] Running baseline 2: Winkler linear ...")
    b2 = baseline_winkler_linear(df)

    print("\n[baselines] Running baseline 3: Full feature OLS ...")
    b3 = baseline_full_ols(df)

    print("[baselines] Running baseline 4: Persistence ...")
    b4 = baseline_persistence(df)

    all_results = {
        "historical_mean": b1,
        "winkler_linear":  b2,
        "full_ols":        b3,
        "persistence":     b4,
        "_meta": {
            "train_years": f"{train['year'].min()}–{train['year'].max()}",
            "test_years":  f"{test['year'].min()}–{test['year'].max()}",
            "train_cutoff": TRAIN_CUTOFF,
            "rolling_window": ROLLING_WINDOW,
            "features_used_full_ols": CONTINUOUS_FEATURES,
        },
    }

    print_table(all_results)

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\n[baselines] Wrote results → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print(f"\n[baselines] Dry run — pass --apply to write models/baselines.json")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run baseline ladder for vintage prediction.")
    parser.add_argument("--apply", action="store_true", help="Write results to models/baselines.json.")
    args = parser.parse_args()
    run_baselines(apply=args.apply)

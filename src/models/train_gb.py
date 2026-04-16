"""Train a multi-output gradient boosting model for vintage prediction.

Predicts brix and tons_crushed jointly using LightGBM with a MultiOutputRegressor
wrapper. Models are variety-stratified: one model per variety, each producing
two outputs (brix, tons_crushed).

Feature engineering
-------------------
- Lag-1 brix and lag-1 tons_crushed added as features (from EDA #36 autocorrelation finding)
- Variety one-hot encoded (within-variety models, so this is a no-op but kept for consistency)
- drought_class ordinal encoded by severity_score (already numeric in feature matrix)
- AVA-level features: awc_r, claytotal_r, texcl one-hot encoded

Hyperparameter tuning
---------------------
Time-series expanding-window CV (same folds as baselines.py) over a small grid.
Best params selected by mean RMSE across folds and both targets.

Artifacts saved to models/
--------------------------
- gradient_boosting_model.pkl  — {variety: fitted MultiOutputRegressor}
- feature_names.json           — ordered feature list used at training time
- training_config.json         — hyperparameters, split metadata, CV scores

Usage
-----
    python -m src.models.train_gb            # dry run (train + evaluate, no save)
    python -m src.models.train_gb --apply    # train, evaluate, save artifacts
"""

import argparse
import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import OneHotEncoder

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
FEATURE_MATRIX = _ROOT / "data" / "processed" / "feature_matrix.parquet"
CDFA_CLEAN     = _ROOT / "data" / "processed" / "cdfa_clean.parquet"
BASELINES_JSON = _ROOT / "models" / "baselines.json"
MODEL_PATH     = _ROOT / "models" / "gradient_boosting_model.pkl"
FEAT_NAMES_PATH = _ROOT / "models" / "feature_names.json"
CONFIG_PATH    = _ROOT / "models" / "training_config.json"

TRAIN_CUTOFF = 2019
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

CATEGORICAL_FEATURES = ["texcl", "drainagecl"]

# Hyperparameter search grid
PARAM_GRID = [
    {"n_estimators": 100, "learning_rate": 0.05, "max_depth": 3,  "min_child_samples": 5,  "subsample": 0.8},
    {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 3,  "min_child_samples": 5,  "subsample": 0.8},
    {"n_estimators": 100, "learning_rate": 0.10, "max_depth": 4,  "min_child_samples": 5,  "subsample": 0.8},
    {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 4,  "min_child_samples": 3,  "subsample": 0.9},
    {"n_estimators": 100, "learning_rate": 0.05, "max_depth": 2,  "min_child_samples": 5,  "subsample": 1.0},
]


# ---------------------------------------------------------------------------
# Data loading and feature engineering
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load feature matrix joined with CDFA targets, add lag features.

    Returns:
        DataFrame with one row per (year × variety × AVA), including
        lag-1 brix and lag-1 tons_crushed computed within each (variety × AVA).
    """
    features = pd.read_parquet(FEATURE_MATRIX)
    cdfa = pd.read_parquet(CDFA_CLEAN)[["year", "variety", "brix", "tons_crushed"]]

    # Join CDFA onto Napa Valley AVA (district-level targets)
    napa = features[features["ava_district"] == "Napa Valley"].copy()
    df = cdfa.merge(napa.drop(columns=["ava_district"]), on="year", how="inner")
    df = df.sort_values(["variety", "year"]).reset_index(drop=True)

    # Lag features within each variety
    for tgt in TARGETS:
        df[f"{tgt}_lag1"] = df.groupby("variety")[tgt].shift(1)

    return df


def build_feature_matrix(
    df: pd.DataFrame,
    encoder: OneHotEncoder | None = None,
    fit_encoder: bool = False,
) -> tuple[pd.DataFrame, OneHotEncoder]:
    """Encode categorical features and return the full feature matrix.

    Args:
        df: Input DataFrame with raw features.
        encoder: Fitted OneHotEncoder, or None to create a new one.
        fit_encoder: If True, fit the encoder on df before transforming.

    Returns:
        (X, encoder) where X has numeric + one-hot columns.
    """
    # Fill missing categoricals with 'Unknown'
    cat_df = df[CATEGORICAL_FEATURES].fillna("Unknown")

    if fit_encoder or encoder is None:
        encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
        encoder.fit(cat_df)

    cat_encoded = encoder.transform(cat_df)
    cat_cols = encoder.get_feature_names_out(CATEGORICAL_FEATURES).tolist()
    cat_frame = pd.DataFrame(cat_encoded, columns=cat_cols, index=df.index)

    num_frame = df[NUMERIC_FEATURES].copy()
    return pd.concat([num_frame, cat_frame], axis=1), encoder


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
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
# Hyperparameter tuning via time-series CV
# ---------------------------------------------------------------------------

def tune_hyperparams(
    df: pd.DataFrame,
    variety: str,
) -> dict:
    """Select best hyperparameters via expanding-window CV for one variety.

    Scores each param combination by mean RMSE across CV folds and both targets.

    Args:
        df: Full dataset (all varieties).
        variety: Variety to tune for.

    Returns:
        Best param dict from PARAM_GRID.
    """
    sub = df[df["variety"] == variety].sort_values("year").reset_index(drop=True)
    best_params = PARAM_GRID[0]
    best_score = float("inf")

    for params in PARAM_GRID:
        fold_scores = []
        for train_end, test_end in CV_FOLDS:
            cv_train = sub[sub["year"] <= train_end].dropna(subset=NUMERIC_FEATURES + TARGETS)
            cv_test  = sub[(sub["year"] > train_end) & (sub["year"] <= test_end)]
            if len(cv_train) < 10 or len(cv_test) < 1:
                continue

            X_train, enc = build_feature_matrix(cv_train, fit_encoder=True)
            X_test, _    = build_feature_matrix(cv_test, encoder=enc)
            y_train = cv_train[TARGETS].values

            # Drop rows with NaN in test features
            valid_mask = ~np.isnan(X_test.values).any(axis=1)
            if valid_mask.sum() < 1:
                continue

            model = MultiOutputRegressor(
                LGBMRegressor(verbose=-1, random_state=42, **params)
            )
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test[valid_mask])
            y_true = cv_test[TARGETS].values[valid_mask]

            fold_rmse = np.mean([
                np.sqrt(mean_squared_error(y_true[:, i], y_pred[:, i]))
                for i in range(len(TARGETS))
            ])
            fold_scores.append(fold_rmse)

        if fold_scores:
            mean_score = np.mean(fold_scores)
            if mean_score < best_score:
                best_score = mean_score
                best_params = params

    return best_params


# ---------------------------------------------------------------------------
# Training and evaluation
# ---------------------------------------------------------------------------

def train_variety(
    df: pd.DataFrame,
    variety: str,
    params: dict,
) -> tuple[MultiOutputRegressor, OneHotEncoder, list[str]]:
    """Fit a multi-output GBM on the full training set for one variety.

    Args:
        df: Full dataset.
        variety: Variety to train on.
        params: LightGBM hyperparameters.

    Returns:
        (fitted model, fitted encoder, feature names list)
    """
    sub = df[(df["variety"] == variety) & (df["year"] <= TRAIN_CUTOFF)]
    sub = sub.dropna(subset=NUMERIC_FEATURES + TARGETS)

    X_train, encoder = build_feature_matrix(sub, fit_encoder=True)
    y_train = sub[TARGETS].values

    model = MultiOutputRegressor(LGBMRegressor(verbose=-1, random_state=42, **params))
    model.fit(X_train, y_train)

    return model, encoder, list(X_train.columns)


def evaluate(
    model: MultiOutputRegressor,
    encoder: OneHotEncoder,
    df: pd.DataFrame,
    variety: str,
) -> dict[str, dict[str, float]]:
    """Evaluate model on holdout test set for one variety.

    Args:
        model: Fitted MultiOutputRegressor.
        encoder: Fitted OneHotEncoder.
        df: Full dataset.
        variety: Variety to evaluate.

    Returns:
        {target: metrics_dict}
    """
    sub = df[(df["variety"] == variety) & (df["year"] > TRAIN_CUTOFF)]
    X_test, _ = build_feature_matrix(sub, encoder=encoder)
    valid_mask = ~np.isnan(X_test.values).any(axis=1)

    results = {}
    if valid_mask.sum() < 1:
        for tgt in TARGETS:
            results[tgt] = {"rmse": float("nan"), "mae": float("nan"), "r2": float("nan"), "n": 0}
        return results

    y_pred = model.predict(X_test[valid_mask])
    y_true = sub[TARGETS].values[valid_mask]

    for i, tgt in enumerate(TARGETS):
        results[tgt] = metrics(y_true[:, i], y_pred[:, i])

    return results


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------

def load_baseline_metrics() -> dict | None:
    """Load holdout metrics from baselines.json if it exists."""
    if not BASELINES_JSON.exists():
        return None
    with open(BASELINES_JSON) as f:
        return json.load(f)


def print_comparison(gbm_results: dict, baselines: dict | None) -> None:
    """Print GBM results alongside baseline holdout metrics."""
    baseline_keys   = ["null", "historical_mean", "winkler_linear", "full_ols", "persistence"]
    baseline_labels = ["Null", "Hist. Mean", "Winkler OLS", "Full OLS", "Persistence"]

    for tgt in TARGETS:
        print(f"\n{'='*72}")
        print(f"  {tgt.upper()} — holdout RMSE comparison (test 2020–2024)")
        print(f"{'='*72}")
        print(f"  {'Model':<20}  {'Cab Sauv':>10}  {'Pinot Noir':>10}  {'Chardonnay':>10}")
        print(f"  {'-'*55}")

        # GBM row
        row = f"  {'GBM (this run)':<20}"
        for variety in VARIETIES:
            rmse = gbm_results.get(variety, {}).get(tgt, {}).get("rmse", float("nan"))
            marker = " ✓" if not _is_nan(rmse) and _beats_best_baseline(rmse, tgt, variety, baselines) else "  "
            row += f"  {rmse:>8.3f}{marker}"
        print(row)

        print(f"  {'—'*55}")

        # Baseline rows
        if baselines:
            for key, label in zip(baseline_keys, baseline_labels):
                row = f"  {label:<20}"
                for variety in VARIETIES:
                    rmse = baselines.get(key, {}).get(variety, {}).get(tgt, {}).get("rmse", float("nan"))
                    row += f"  {rmse:>10.3f}"
                print(row)
        else:
            print("  (baselines.json not found — run src.models.baselines --apply first)")


def _is_nan(v) -> bool:
    try:
        return np.isnan(v)
    except Exception:
        return True


def _beats_best_baseline(rmse: float, tgt: str, variety: str, baselines: dict | None) -> bool:
    """Return True if rmse is lower than all baseline holdout RMSEs."""
    if not baselines:
        return False
    best = min(
        baselines.get(k, {}).get(variety, {}).get(tgt, {}).get("rmse", float("inf"))
        for k in ["null", "historical_mean", "winkler_linear", "full_ols", "persistence"]
        if not _is_nan(baselines.get(k, {}).get(variety, {}).get(tgt, {}).get("rmse", float("nan")))
    )
    return rmse < best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def train_and_evaluate(apply: bool = False) -> dict:
    """Full train + tune + evaluate pipeline.

    Args:
        apply: If True, save model artifacts to models/.

    Returns:
        Dict of {variety: {target: metrics}} on holdout set.
    """
    print("[gb] Loading data ...")
    df = load_data()
    train_df = df[df["year"] <= TRAIN_CUTOFF]
    test_df  = df[df["year"] >  TRAIN_CUTOFF]
    print(f"[gb] Train: {train_df['year'].nunique()} years | "
          f"Test: {test_df['year'].nunique()} years | "
          f"Lag-1 coverage: {df['brix_lag1'].notna().sum()}/{len(df)} rows")

    all_models   = {}
    all_encoders = {}
    all_params   = {}
    all_feat_names = {}
    gbm_results  = {}

    for variety in VARIETIES:
        print(f"\n[gb] {variety}")

        print(f"  Tuning hyperparameters via {len(CV_FOLDS)}-fold CV ...")
        best_params = tune_hyperparams(df, variety)
        all_params[variety] = best_params
        print(f"  Best params: {best_params}")

        print(f"  Training on 1991–{TRAIN_CUTOFF} ...")
        model, encoder, feat_names = train_variety(df, variety, best_params)
        all_models[variety]    = model
        all_encoders[variety]  = encoder
        all_feat_names[variety] = feat_names

        print(f"  Evaluating on {TRAIN_CUTOFF+1}–{test_df['year'].max()} ...")
        results = evaluate(model, encoder, df, variety)
        gbm_results[variety] = results

        for tgt in TARGETS:
            m = results[tgt]
            print(f"  {tgt:<15} RMSE={m['rmse']:.3f}  MAE={m['mae']:.3f}  R²={m['r2']:.3f}  n={m['n']}")

    baselines = load_baseline_metrics()
    print_comparison(gbm_results, baselines)

    if apply:
        _ROOT.joinpath("models").mkdir(exist_ok=True)

        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"models": all_models, "encoders": all_encoders}, f)
        print(f"\n[gb] Saved model → {MODEL_PATH.relative_to(_ROOT)}")

        with open(FEAT_NAMES_PATH, "w") as f:
            json.dump(all_feat_names, f, indent=2)
        print(f"[gb] Saved feature names → {FEAT_NAMES_PATH.relative_to(_ROOT)}")

        config = {
            "train_cutoff":      TRAIN_CUTOFF,
            "train_years":       f"{train_df['year'].min()}–{TRAIN_CUTOFF}",
            "test_years":        f"{test_df['year'].min()}–{test_df['year'].max()}",
            "targets":           TARGETS,
            "numeric_features":  NUMERIC_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
            "cv_folds":          [{"train_end": a, "test_end": b} for a, b in CV_FOLDS],
            "best_params":       all_params,
            "holdout_metrics":   gbm_results,
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        print(f"[gb] Saved config → {CONFIG_PATH.relative_to(_ROOT)}")
    else:
        print("\n[gb] Dry run — pass --apply to save artifacts.")

    return gbm_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train gradient boosting model for vintage prediction.")
    parser.add_argument("--apply", action="store_true", help="Save trained model artifacts to models/.")
    args = parser.parse_args()
    train_and_evaluate(apply=args.apply)

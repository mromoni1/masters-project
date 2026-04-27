"""Model prediction and retrospective analysis generation."""

import json
import pickle
import warnings
from pathlib import Path

import anthropic
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

_bundle: dict | None = None
_features: pd.DataFrame | None = None
_metrics: dict | None = None

NUM_COLS = [
    "gdd", "frost_days", "heat_stress_days", "tmax_veraison",
    "precip_winter", "eto_season", "severity_score", "awc_r", "claytotal_r",
]


def _load() -> None:
    global _bundle, _features, _metrics
    if _bundle is not None:
        return
    with open(ROOT / "models/gradient_boosting_model.pkl", "rb") as f:
        _bundle = pickle.load(f)
    _features = pd.read_parquet(ROOT / "data/processed/feature_matrix.parquet")
    with open(ROOT / "models/evaluation_metrics.json") as f:
        _metrics = json.load(f)


def _extract_features(year: int, variety: str) -> tuple[np.ndarray, dict]:
    df = _features
    v = variety.lower().replace(" ", "_")

    cur = df[df["year"] == year]
    if cur.empty:
        raise ValueError(f"No climate data available for {year}.")

    num = cur[NUM_COLS].mean()
    texcl = cur["texcl"].mode()[0]
    drainagecl = cur["drainagecl"].mode()[0]

    prev = df[df["year"] == year - 1]
    if prev.empty:
        brix_lag = df[f"brix_{v}"].dropna().mean()
        tons_lag = df[f"tons_crushed_{v}"].dropna().mean()
    else:
        brix_lag = prev[f"brix_{v}"].dropna().mean()
        tons_lag = prev[f"tons_crushed_{v}"].dropna().mean()

    climate = {
        "gdd": round(float(num["gdd"]), 1),
        "frost_days": int(num["frost_days"]),
        "heat_stress_days": int(num["heat_stress_days"]),
        "tmax_veraison": round(float(num["tmax_veraison"]), 1),
        "precip_winter": round(float(num["precip_winter"]), 1),
        "severity_score": int(num["severity_score"]),
    }

    enc = _bundle["encoders"][variety]
    cat_encoded = enc.transform(
        pd.DataFrame([[texcl, drainagecl]], columns=["texcl", "drainagecl"])
    )
    num_row = np.array([[
        num["gdd"], num["frost_days"], num["heat_stress_days"],
        num["tmax_veraison"], num["precip_winter"], num["eto_season"],
        num["severity_score"], num["awc_r"], num["claytotal_r"],
        brix_lag, tons_lag,
    ]])
    return np.hstack([num_row, cat_encoded]), climate


def _get_actuals(year: int, variety: str) -> dict:
    df = _features
    v = variety.lower().replace(" ", "_")
    cur = df[df["year"] == year]
    return {
        "brix": round(float(cur[f"brix_{v}"].dropna().mean()), 1),
        "tons": round(float(cur[f"tons_crushed_{v}"].dropna().mean()), 0),
    }


def _ten_year_avg(variety: str, year: int) -> dict:
    df = _features
    v = variety.lower().replace(" ", "_")
    window = df[(df["year"] >= year - 10) & (df["year"] < year)]
    return {
        "brix": round(float(window[f"brix_{v}"].dropna().mean()), 1),
        "tons": round(float(window[f"tons_crushed_{v}"].dropna().mean()), 0),
    }


def _call_claude(
    client: anthropic.Anthropic, *,
    variety: str, year: int,
    brix_pred: float, brix_range: tuple,
    tons_pred: float, tons_range: tuple,
    brix_actual: float, tons_actual: float,
    climate: dict, avg: dict,
) -> str:
    brix_delta = round(brix_actual - brix_pred, 1)
    tons_delta = round(tons_actual - tons_pred, 0)
    brix_in_range = brix_range[0] <= brix_actual <= brix_range[1]
    tons_in_range = tons_range[0] <= tons_actual <= tons_range[1]

    prompt = f"""\
You are a viticulture data analyst reviewing a historical Napa Valley growing season.
Write a concise, engaging retrospective analysis in plain prose — no bullet points, no headers.

VARIETY: {variety}
SEASON YEAR: {year}

CLIMATE:
- Growing degree days: {climate['gdd']} (historical avg ~1800)
- Heat stress days (>35°C): {climate['heat_stress_days']}
- Late-frost days (Mar–May): {climate['frost_days']}
- Mean tmax at veraison (Jul–Aug): {climate['tmax_veraison']}°C
- Winter precipitation (Oct–Mar): {climate['precip_winter']} mm
- Drought severity: {climate['severity_score']}/5

MODEL PREDICTION (blind forecast from season-start features):
- Brix: {brix_pred:.1f}°Bx (range {brix_range[0]}–{brix_range[1]})
- Tonnage: {tons_pred:,.0f} tons (range {tons_range[0]:,.0f}–{tons_range[1]:,.0f})

ACTUAL OUTCOME (CDFA Grape Crush Report):
- Brix: {brix_actual:.1f}°Bx  ({'within predicted range' if brix_in_range else f'{"+" if brix_delta > 0 else ""}{brix_delta:+.1f} vs prediction'})
- Tonnage: {tons_actual:,.0f} tons  ({'within predicted range' if tons_in_range else f'{"+" if tons_delta > 0 else ""}{tons_delta:+,.0f} vs prediction'})

10-YEAR AVERAGE (prior to {year}):
- Brix: {avg['brix']}°Bx
- Tonnage: {avg['tons']:,.0f} tons

Write 3 sentences:
1. What defined this season's climate character and how it compares to the historical average.
2. How well the model tracked reality — if Brix and tonnage diverged differently, explain what the \
climate data suggests about why.
3. What makes this vintage stand out or blend into the record.
Output only the analysis — no labels, no preamble."""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=350,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def generate(variety: str, year: int, api_key: str) -> dict:
    _load()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        feature_row, climate = _extract_features(year, variety)
        preds = _bundle["models"][variety].predict(feature_row)[0]

    brix_pred = float(preds[0])
    tons_pred = max(0.0, float(preds[1]))

    variety_metrics = (_metrics or {}).get("elastic_net_delta", {}).get(variety, {})
    brix_rmse = variety_metrics.get("brix", {}).get("rmse", 0.6)
    tons_rmse = variety_metrics.get("tons_crushed", {}).get("rmse", 15000.0)

    brix_range = (round(brix_pred - brix_rmse, 1), round(brix_pred + brix_rmse, 1))
    tons_range = (round(max(0.0, tons_pred - tons_rmse), 0), round(tons_pred + tons_rmse, 0))

    actuals = _get_actuals(year, variety)
    avg = _ten_year_avg(variety, year)

    client = anthropic.Anthropic(api_key=api_key)
    analysis = _call_claude(
        client,
        variety=variety, year=year,
        brix_pred=brix_pred, brix_range=brix_range,
        tons_pred=tons_pred, tons_range=tons_range,
        brix_actual=actuals["brix"], tons_actual=actuals["tons"],
        climate=climate, avg=avg,
    )

    return {
        "variety": variety,
        "year": year,
        "brix_predicted": round(brix_pred, 1),
        "brix_range": list(brix_range),
        "tonnage_predicted": round(tons_pred, 0),
        "tonnage_range": list(tons_range),
        "brix_actual": actuals["brix"],
        "tonnage_actual": actuals["tons"],
        "climate": climate,
        "analysis": analysis,
    }

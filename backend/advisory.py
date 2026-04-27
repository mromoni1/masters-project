"""Model prediction and Claude advisory generation."""

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


def _ten_year_avg(variety: str, year: int) -> dict:
    df = _features
    v = variety.lower().replace(" ", "_")
    window = df[(df["year"] >= year - 10) & (df["year"] < year)]
    return {
        "brix": round(float(window[f"brix_{v}"].dropna().mean()), 1),
        "tons": round(float(window[f"tons_crushed_{v}"].dropna().mean()), 0),
    }


def _confidence(severity: int) -> tuple[str, str]:
    if severity <= 1:
        return "high", "Season follows a recognizable pattern with all key features present."
    if severity <= 3:
        return "moderate", "One or more climate stressors were elevated; estimates carry added uncertainty."
    return "low", "Unusual season with multiple climate stressors — the model is extrapolating beyond normal patterns."


def _harvest_window(brix: float) -> str:
    if brix < 22:
        return "early to mid-September"
    if brix < 24:
        return "mid to late September"
    if brix < 26:
        return "late September to early October"
    return "early to mid-October"


def _call_claude(client: anthropic.Anthropic, *, variety: str, year: int,
                 brix_pred: float, brix_range: tuple, tons_pred: float,
                 tons_range: tuple, harvest_window: str, confidence: str,
                 confidence_note: str, climate: dict, avg: dict) -> str:
    confidence_instruction = {
        "high": "The model is confident — write in a direct, assured tone.",
        "moderate": "Acknowledge the added uncertainty naturally in one phrase (e.g., 'though conditions this season add some variability').",
        "low": "Lead with the uncertainty in plain language before giving the estimate — do not bury the caveat.",
    }[confidence]

    prompt = f"""\
You are a warm, plain-spoken harvest advisor for small Napa Valley vintners.
Write a friendly, conversational advisory grounded strictly in the model output below.
Do not add general agronomic advice beyond what the data supports.
Do not use bullet points, headers, or labels — write flowing prose only.

VARIETY: {variety}
SEASON YEAR: {year}

CLIMATE SUMMARY:
- Growing degree days: {climate['gdd']} (historical Napa avg ~1800)
- Heat stress days (>35°C, Apr–Oct): {climate['heat_stress_days']}
- Late-frost days (tmin <0°C, Mar–May): {climate['frost_days']}
- Mean max temp at veraison (Jul–Aug): {climate['tmax_veraison']}°C
- Winter precipitation (Oct–Mar): {climate['precip_winter']} mm
- Drought severity score: {climate['severity_score']}/5

MODEL PREDICTIONS:
- Projected Brix: {brix_pred:.1f}°Bx (range {brix_range[0]}–{brix_range[1]})
- Projected tonnage: {tons_pred:,.0f} tons (range {tons_range[0]:,.0f}–{tons_range[1]:,.0f})
- 10-year average Brix: {avg['brix']}°Bx
- 10-year average tonnage: {avg['tons']:,.0f} tons
- Estimated harvest window: {harvest_window}

Confidence guidance: {confidence_instruction}

Write 2–3 sentences in second person ("your block", "consider").
Cover: (1) where Brix is trending vs the 10-year average, (2) tonnage outlook, \
(3) when to start harvest checks.
Output only the advisory text."""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
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

    confidence, confidence_note = _confidence(climate["severity_score"])
    harvest_window = _harvest_window(brix_pred)
    avg = _ten_year_avg(variety, year)

    client = anthropic.Anthropic(api_key=api_key)
    advisory_text = _call_claude(
        client,
        variety=variety, year=year,
        brix_pred=brix_pred, brix_range=brix_range,
        tons_pred=tons_pred, tons_range=tons_range,
        harvest_window=harvest_window,
        confidence=confidence, confidence_note=confidence_note,
        climate=climate, avg=avg,
    )

    return {
        "variety": variety,
        "year": year,
        "brix_predicted": round(brix_pred, 1),
        "brix_range": list(brix_range),
        "tonnage_predicted": round(tons_pred, 0),
        "tonnage_range": list(tons_range),
        "harvest_window": harvest_window,
        "confidence": confidence,
        "advisory_text": advisory_text,
    }

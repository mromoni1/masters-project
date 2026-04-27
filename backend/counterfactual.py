"""Counterfactual 'what if' prediction engine."""

import warnings
from pathlib import Path

import anthropic
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Re-use the same loader/state from advisory.py
import advisory as _adv


CLIMATE_COLS = [
    "gdd", "frost_days", "heat_stress_days",
    "tmax_veraison", "precip_winter", "eto_season", "severity_score",
]

CLIMATE_LABELS: dict[str, str] = {
    "gdd": "Growing Degree Days",
    "frost_days": "Frost Days (Mar–May)",
    "heat_stress_days": "Heat Stress Days",
    "tmax_veraison": "Tmax at Veraison (°C)",
    "precip_winter": "Winter Precip (mm)",
    "eto_season": "Seasonal ETo",
    "severity_score": "Drought Severity (0–5)",
}


def _predict_for(variety: str, year: int, climate_override: dict | None = None) -> tuple[float, float, dict]:
    """Return (brix_pred, tons_pred, climate_dict) for variety/year, optionally with swapped climate."""
    _adv._load()
    df = _adv._features
    v = variety.lower().replace(" ", "_")

    cur = df[df["year"] == year]
    if cur.empty:
        raise ValueError(f"No data for {year}.")

    num = cur[_adv.NUM_COLS].mean().to_dict()

    # Swap climate columns if override provided
    if climate_override:
        for col in CLIMATE_COLS:
            if col in climate_override:
                num[col] = climate_override[col]

    texcl = cur["texcl"].mode()[0]
    drainagecl = cur["drainagecl"].mode()[0]

    prev = df[df["year"] == year - 1]
    if prev.empty:
        brix_lag = df[f"brix_{v}"].dropna().mean()
        tons_lag = df[f"tons_crushed_{v}"].dropna().mean()
    else:
        brix_lag = prev[f"brix_{v}"].dropna().mean()
        tons_lag = prev[f"tons_crushed_{v}"].dropna().mean()

    enc = _adv._bundle["encoders"][variety]
    cat_encoded = enc.transform(
        pd.DataFrame([[texcl, drainagecl]], columns=["texcl", "drainagecl"])
    )
    num_row = np.array([[
        num["gdd"], num["frost_days"], num["heat_stress_days"],
        num["tmax_veraison"], num["precip_winter"], num["eto_season"],
        num["severity_score"], num["awc_r"], num["claytotal_r"],
        brix_lag, tons_lag,
    ]])
    feature_row = np.hstack([num_row, cat_encoded])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        preds = _adv._bundle["models"][variety].predict(feature_row)[0]

    climate_out = {
        "gdd": round(float(num["gdd"]), 1),
        "frost_days": int(num["frost_days"]),
        "heat_stress_days": int(num["heat_stress_days"]),
        "tmax_veraison": round(float(num["tmax_veraison"]), 1),
        "precip_winter": round(float(num["precip_winter"]), 1),
        "severity_score": int(num["severity_score"]),
    }

    return float(preds[0]), max(0.0, float(preds[1])), climate_out


def _get_climate_means(year: int) -> dict:
    """Return mean climate values for a given year."""
    _adv._load()
    df = _adv._features
    cur = df[df["year"] == year]
    if cur.empty:
        raise ValueError(f"No climate data for {year}.")
    return {col: float(cur[col].mean()) for col in CLIMATE_COLS}


def _call_claude(
    client: anthropic.Anthropic, *,
    variety: str,
    base_year: int,
    climate_year: int,
    base_brix: float,
    base_tons: float,
    cf_brix: float,
    cf_tons: float,
    base_climate: dict,
    cf_climate: dict,
) -> str:
    brix_delta = round(cf_brix - base_brix, 1)
    tons_delta = round(cf_tons - base_tons, 0)

    diffs = []
    for col in CLIMATE_COLS:
        b = base_climate.get(col, 0)
        c = cf_climate.get(col, 0)
        if col in ("gdd",):
            d = round(c - b, 0)
        else:
            d = round(c - b, 1)
        if abs(d) > 0:
            sign = "+" if d > 0 else ""
            diffs.append(f"  {CLIMATE_LABELS[col]}: {sign}{d}")

    diff_str = "\n".join(diffs) if diffs else "  (minimal differences)"

    prompt = f"""\
You are a viticulture data analyst explaining a model-based counterfactual scenario.
Write 3 sentences in plain prose — no bullet points, no headers.

SCENARIO: What would {variety} in {base_year} have looked like with {climate_year}'s climate?

CLIMATE DIFFERENCES ({climate_year} vs {base_year}):
{diff_str}

PREDICTION CHANGE:
- Brix: {base_brix:.1f}°Bx → {cf_brix:.1f}°Bx ({'+' if brix_delta >= 0 else ''}{brix_delta:+.1f})
- Tonnage: {base_tons:,.0f} → {cf_tons:,.0f} tons ({'+' if tons_delta >= 0 else ''}{tons_delta:+,.0f})

Write:
1. Which climate differences drive the change and which direction they push Brix and yield.
2. The net effect on fruit quality and volume.
3. What this reveals about {variety}'s sensitivity to the most changed factor.
Output only the analysis."""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=280,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def run(variety: str, base_year: int, climate_year: int, api_key: str) -> dict:
    """Run counterfactual: variety/base_year with climate_year's climate substituted."""
    _adv._load()

    # Original prediction (base year climate)
    base_brix, base_tons, base_climate = _predict_for(variety, base_year)

    # Get climate_year's climate values
    cf_climate_values = _get_climate_means(climate_year)

    # Counterfactual prediction (swapped climate)
    cf_brix, cf_tons, cf_climate = _predict_for(variety, base_year, climate_override=cf_climate_values)

    client = anthropic.Anthropic(api_key=api_key)
    analysis = _call_claude(
        client,
        variety=variety,
        base_year=base_year,
        climate_year=climate_year,
        base_brix=base_brix,
        base_tons=base_tons,
        cf_brix=cf_brix,
        cf_tons=cf_tons,
        base_climate=base_climate,
        cf_climate=cf_climate,
    )

    # Build climate comparison rows
    climate_diff = []
    for col in CLIMATE_COLS:
        b_val = base_climate.get(col, 0)
        c_val = cf_climate.get(col, 0)
        climate_diff.append({
            "label": CLIMATE_LABELS[col],
            "base": b_val,
            "counterfactual": c_val,
            "delta": round(c_val - b_val, 1),
        })

    return {
        "variety": variety,
        "base_year": base_year,
        "climate_year": climate_year,
        "base": {
            "brix": round(base_brix, 1),
            "tons": round(base_tons, 0),
            "climate": base_climate,
        },
        "counterfactual": {
            "brix": round(cf_brix, 1),
            "tons": round(cf_tons, 0),
            "climate": cf_climate,
        },
        "climate_diff": climate_diff,
        "analysis": analysis,
    }

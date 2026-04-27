"""Climate trend data and narrative summary generation."""

from pathlib import Path

import anthropic
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

_df: pd.DataFrame | None = None


def _load() -> pd.DataFrame:
    global _df
    if _df is None:
        _df = pd.read_parquet(ROOT / "data/processed/feature_matrix.parquet")
    return _df


def get_data() -> dict:
    """Return year-level aggregated trend data for all climate and yield series."""
    df = _load()
    agg = (
        df.groupby("year")
        .agg(
            gdd=("gdd", "mean"),
            heat_stress_days=("heat_stress_days", "mean"),
            frost_days=("frost_days", "mean"),
            precip_winter=("precip_winter", "mean"),
            severity_score=("severity_score", "mean"),
            brix_cab=("brix_cabernet_sauvignon", "mean"),
            brix_pn=("brix_pinot_noir", "mean"),
            brix_chard=("brix_chardonnay", "mean"),
            tons_cab=("tons_crushed_cabernet_sauvignon", "mean"),
            tons_pn=("tons_crushed_pinot_noir", "mean"),
            tons_chard=("tons_crushed_chardonnay", "mean"),
        )
        .reset_index()
    )

    records = []
    for _, row in agg.iterrows():
        records.append({
            "year": int(row["year"]),
            "gdd": round(float(row["gdd"]), 1),
            "heat_stress_days": round(float(row["heat_stress_days"]), 1),
            "frost_days": round(float(row["frost_days"]), 1),
            "precip_winter": round(float(row["precip_winter"]), 1),
            "severity_score": round(float(row["severity_score"]), 2),
            "brix_cab": round(float(row["brix_cab"]), 1) if pd.notna(row["brix_cab"]) else None,
            "brix_pn": round(float(row["brix_pn"]), 1) if pd.notna(row["brix_pn"]) else None,
            "brix_chard": round(float(row["brix_chard"]), 1) if pd.notna(row["brix_chard"]) else None,
            "tons_cab": round(float(row["tons_cab"]), 0) if pd.notna(row["tons_cab"]) else None,
            "tons_pn": round(float(row["tons_pn"]), 0) if pd.notna(row["tons_pn"]) else None,
            "tons_chard": round(float(row["tons_chard"]), 0) if pd.notna(row["tons_chard"]) else None,
        })

    return {"years": records}


def get_narrative(api_key: str) -> str:
    """Generate a Claude narrative summarizing 34-year climate trends."""
    df = _load()
    agg = (
        df.groupby("year")
        .agg(
            gdd=("gdd", "mean"),
            heat_stress_days=("heat_stress_days", "mean"),
            frost_days=("frost_days", "mean"),
            precip_winter=("precip_winter", "mean"),
            severity_score=("severity_score", "mean"),
            brix_cab=("brix_cabernet_sauvignon", "mean"),
            brix_chard=("brix_chardonnay", "mean"),
        )
        .reset_index()
    )

    # Compute simple trend slopes for the prompt
    def _slope(series: pd.Series) -> float:
        x = pd.Series(range(len(series)))
        return round(float((series - series.mean()).cov(x - x.mean()) / x.var()), 3)

    gdd_slope = _slope(agg["gdd"])
    heat_slope = _slope(agg["heat_stress_days"])
    precip_slope = _slope(agg["precip_winter"])
    brix_cab_slope = _slope(agg["brix_cab"].dropna())
    severity_slope = _slope(agg["severity_score"])

    early = agg[agg["year"] <= 2001]
    late = agg[agg["year"] >= 2014]

    prompt = f"""\
You are a viticulture climate analyst. Summarize what the 34-year Napa Valley record \
(1991–2024) reveals about climate change and its effects on wine grape growing. \
Write 4–5 sentences in plain, engaging prose — no bullet points, no headers.

KEY STATISTICS:
- GDD trend: {gdd_slope:+.1f} degree-days/year (early avg {early['gdd'].mean():.0f}, \
late avg {late['gdd'].mean():.0f})
- Heat stress days trend: {heat_slope:+.2f} days/year
- Winter precipitation trend: {precip_slope:+.1f} mm/year (early avg \
{early['precip_winter'].mean():.0f} mm, late avg {late['precip_winter'].mean():.0f} mm)
- Drought severity trend: {severity_slope:+.3f}/year (scale 0–5)
- Cabernet Brix trend: {brix_cab_slope:+.3f}°Bx/year

Address: warming trajectory, changing drought/precipitation patterns, \
and what this means for growers. Keep it informative but accessible."""

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()

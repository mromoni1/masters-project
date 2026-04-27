"""Q&A over the Napa Valley harvest dataset using Claude."""

from pathlib import Path

import anthropic
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

_context: str | None = None


def _build_context() -> str:
    df = pd.read_parquet(ROOT / "data/processed/feature_matrix.parquet")

    agg = (
        df.groupby("year")
        .agg(
            gdd=("gdd", "mean"),
            frost_days=("frost_days", "mean"),
            heat_stress_days=("heat_stress_days", "mean"),
            tmax_veraison=("tmax_veraison", "mean"),
            precip_winter=("precip_winter", "mean"),
            severity_score=("severity_score", "mean"),
            brix_cab=("brix_cabernet_sauvignon", "mean"),
            tons_cab=("tons_crushed_cabernet_sauvignon", "mean"),
            brix_pinot=("brix_pinot_noir", "mean"),
            tons_pinot=("tons_crushed_pinot_noir", "mean"),
            brix_chard=("brix_chardonnay", "mean"),
            tons_chard=("tons_crushed_chardonnay", "mean"),
        )
        .round(1)
        .reset_index()
    )

    rows = ["| Year | GDD | Frost days | Heat stress days | Tmax veraison (°C) | Winter precip (mm) | Drought severity | Cab Brix | Cab tons | Pinot Brix | Pinot tons | Chard Brix | Chard tons |"]
    rows.append("|------|-----|------------|-----------------|-------------------|-------------------|-----------------|----------|----------|------------|------------|------------|------------|")
    for _, r in agg.iterrows():
        rows.append(
            f"| {int(r.year)} | {r.gdd} | {r.frost_days} | {r.heat_stress_days} | "
            f"{r.tmax_veraison} | {r.precip_winter} | {int(r.severity_score)} | "
            f"{r.brix_cab} | {r.tons_cab:,.0f} | {r.brix_pinot} | {r.tons_pinot:,.0f} | "
            f"{r.brix_chard} | {r.tons_chard:,.0f} |"
        )

    return "\n".join(rows)


def _get_context() -> str:
    global _context
    if _context is None:
        _context = _build_context()
    return _context


SYSTEM_PROMPT = """\
You are a data analyst assistant for the Napa Vine Advisor project.
You have access to 34 years of Napa Valley harvest and climate data (1991–2024) \
for three varieties: Cabernet Sauvignon, Pinot Noir, and Chardonnay.

Column definitions:
- GDD: growing degree days (base 10°C, Apr–Oct) — higher means warmer season
- Frost days: days with tmin < 0°C, Mar–May — spring frost risk
- Heat stress days: days with tmax > 35°C, Apr–Oct
- Tmax veraison: mean daily max temp Jul–Aug (°C) — critical ripening window
- Winter precip: total Oct–Mar precipitation (mm)
- Drought severity: DWR water year classification 1–5 (5 = critically dry)
- Brix: average sugar content at harvest (°Bx) — higher = riper
- Tons: district-wide crushed tonnage

All climate values are averaged across Napa Valley AVA districts.
All Brix and tonnage values are district-wide averages from the CDFA Grape Crush Report.

DATA:
{data}

Answer questions about this data directly and specifically. \
Cite years and numbers when relevant. \
Keep answers concise — 2–4 sentences unless a comparison or list is clearly asked for. \
Do not speculate beyond what the data shows."""


def reply(messages: list[dict], api_key: str) -> str:
    context = _get_context()
    system = SYSTEM_PROMPT.format(data=context)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=system,
        messages=messages,
    )
    return response.content[0].text.strip()

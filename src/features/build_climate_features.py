"""Build PRISM-derived agroclimatic features for the model feature matrix.

Reads data/processed/prism_clean.parquet and computes one row of engineered
features per (year × AVA district). Output is written to
data/processed/features_climate.parquet.

Features computed
-----------------
All temperature values in prism_clean.parquet are in °C. Precipitation is
in mm.

| Column            | Definition                                      | Window          |
|-------------------|-------------------------------------------------|-----------------|
| gdd               | Growing degree days, base 10 °C, clipped at 0  | Apr 1 – Oct 31  |
| winkler_index     | Same as gdd — explicit Winkler naming           | Apr 1 – Oct 31  |
| frost_days        | Days with tmin < 0 °C                           | Mar 1 – May 31  |
| heat_stress_days  | Days with tmax > 35 °C                          | Apr 1 – Oct 31  |
| precip_winter     | Total precipitation (mm)                        | Oct 1 – Mar 31* |
| tmax_veraison     | Mean daily tmax (°C)                            | Jul 1 – Aug 31  |

*precip_winter for harvest year N uses Oct 1 of year (N-1) through Mar 31
of year N, matching the DWR water year convention.

GDD / Winkler calculation
--------------------------
Daily GDD = max(0, tmean - 10). Winkler index is the seasonal cumulative
sum of daily GDD over Apr 1 – Oct 31. The two columns are numerically
identical; winkler_index is retained for direct comparison against the
industry-standard Winkler region classification (Region I < 1389, …,
Region V > 2222 degree-days Celsius).

Missing day handling
--------------------
Days flagged missing_day=True in prism_clean.parquet have NaN values for
all climate variables. They are excluded from degree-day accumulations and
counts. The column `missing_days_growing` records how many days were
excluded from the Apr–Oct window per (year × AVA). Years with > 14 missing
days (≥ 1 week) in the growing season are flagged in `data_quality_warn`.

Usage
-----
    python -m src.features.build_climate_features            # dry run
    python -m src.features.build_climate_features --apply    # write Parquet
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
PRISM_CLEAN = _ROOT / "data" / "processed" / "prism_clean.parquet"
OUTPUT_PATH = _ROOT / "data" / "processed" / "features_climate.parquet"

START_YEAR = 1991
END_YEAR = 2024

GDD_BASE_C = 10.0
HEAT_STRESS_THRESHOLD_C = 35.0
FROST_THRESHOLD_C = 0.0
MISSING_DAY_WARN_THRESHOLD = 14  # flag years with > this many missing growing-season days


# ---------------------------------------------------------------------------
# Seasonal window helpers
# ---------------------------------------------------------------------------

def _growing_season(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows in Apr 1 – Oct 31 (months 4–10)."""
    return df[df["date"].dt.month.between(4, 10)]


def _frost_window(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows in Mar 1 – May 31 (months 3–5)."""
    return df[df["date"].dt.month.between(3, 5)]


def _veraison_window(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows in Jul 1 – Aug 31 (months 7–8)."""
    return df[df["date"].dt.month.between(7, 8)]


def _winter_precip_rows(df: pd.DataFrame, harvest_year: int) -> pd.DataFrame:
    """Return rows for the dormant-season window preceding harvest_year.

    Window: Oct 1 of (harvest_year - 1) through Mar 31 of harvest_year.

    Args:
        df: Full PRISM DataFrame with a 'date' column (datetime).
        harvest_year: The growing season / harvest calendar year.

    Returns:
        Subset of df covering the dormant season.
    """
    start = pd.Timestamp(harvest_year - 1, 10, 1)
    end = pd.Timestamp(harvest_year, 3, 31)
    return df[(df["date"] >= start) & (df["date"] <= end)]


# ---------------------------------------------------------------------------
# Per-year feature computation
# ---------------------------------------------------------------------------

def _compute_year_ava(year_ava_df: pd.DataFrame, harvest_year: int, full_df: pd.DataFrame, ava: str) -> dict:
    """Compute all features for one (year × AVA district) combination.

    Args:
        year_ava_df: Rows for this harvest year and AVA (all months).
        harvest_year: The calendar / harvest year.
        full_df: Full PRISM DataFrame (needed for winter precip lookback).
        ava: AVA district name.

    Returns:
        Dict of feature values for this (year, ava_district).
    """
    # Exclude missing days before any calculation
    valid = year_ava_df[~year_ava_df["missing_day"]]

    # --- GDD / Winkler (Apr–Oct, valid days only) ---
    gs = _growing_season(valid)
    daily_gdd = np.maximum(0, gs["tmean"] - GDD_BASE_C)
    gdd = float(daily_gdd.sum()) if not gs.empty else float("nan")

    # Count missing days in growing season for quality flag
    gs_all = _growing_season(year_ava_df)
    missing_in_gs = int(gs_all["missing_day"].sum())

    # --- Frost days (Mar–May, valid days only) ---
    fw = _frost_window(valid)
    frost_days = int((fw["tmin"] < FROST_THRESHOLD_C).sum()) if not fw.empty else 0

    # --- Heat stress days (Apr–Oct, valid days only) ---
    heat_stress_days = int((gs["tmax"] > HEAT_STRESS_THRESHOLD_C).sum()) if not gs.empty else 0

    # --- Veraison mean tmax (Jul–Aug, valid days only) ---
    vw = _veraison_window(valid)
    tmax_veraison = float(vw["tmax"].mean()) if not vw.empty else float("nan")

    # --- Winter precipitation (Oct prior – Mar current, valid days only) ---
    wp = _winter_precip_rows(full_df, harvest_year)
    wp_ava = wp[(wp["ava_district"] == ava) & (~wp["missing_day"])]
    precip_winter = float(wp_ava["ppt"].sum()) if not wp_ava.empty else float("nan")

    return {
        "year": harvest_year,
        "ava_district": ava,
        "gdd": round(gdd, 1),
        "winkler_index": round(gdd, 1),       # numerically identical to gdd
        "frost_days": frost_days,
        "heat_stress_days": heat_stress_days,
        "tmax_veraison": round(tmax_veraison, 2),
        "precip_winter": round(precip_winter, 1),
        "missing_days_growing": missing_in_gs,
        "data_quality_warn": missing_in_gs > MISSING_DAY_WARN_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_climate_features(apply: bool = False) -> pd.DataFrame:
    """Compute agroclimatic features from prism_clean.parquet.

    Args:
        apply: If True, write output to data/processed/features_climate.parquet.

    Returns:
        Feature DataFrame with one row per (year × AVA district).
    """
    if not PRISM_CLEAN.exists():
        raise FileNotFoundError(
            f"{PRISM_CLEAN} not found. "
            "Run src/ingestion/ingest_prism.py and src/ingestion/clean_prism.py first."
        )

    print(f"[climate] Loading {PRISM_CLEAN.name} ...")
    prism = pd.read_parquet(PRISM_CLEAN)
    prism["date"] = pd.to_datetime(prism["date"])

    avas = sorted(prism["ava_district"].unique())
    print(f"[climate] {len(prism):,} rows | {len(avas)} AVA districts | "
          f"dates {prism['date'].min().date()} – {prism['date'].max().date()}")

    # Filter to analysis window (need prior-year Oct for winter precip lookback)
    prism_window = prism[prism["date"].dt.year.between(START_YEAR - 1, END_YEAR)]

    records = []
    years = range(START_YEAR, END_YEAR + 1)
    for year in years:
        year_df = prism_window[prism_window["date"].dt.year == year]
        for ava in avas:
            ava_df = year_df[year_df["ava_district"] == ava]
            if ava_df.empty:
                continue
            record = _compute_year_ava(ava_df, year, prism_window, ava)
            records.append(record)

    df = pd.DataFrame(records).sort_values(["year", "ava_district"]).reset_index(drop=True)

    # Summary
    n_warn = df["data_quality_warn"].sum()
    print(f"\n[climate] {len(df)} rows | {df['year'].nunique()} years × {df['ava_district'].nunique()} AVAs")
    print(f"[climate] GDD range       : {df['gdd'].min():.0f} – {df['gdd'].max():.0f} °C·days")
    print(f"[climate] Winkler index   : identical to GDD (base 10 °C, Apr–Oct)")
    print(f"[climate] Frost days      : {df['frost_days'].min()} – {df['frost_days'].max()} days/season")
    print(f"[climate] Heat stress days: {df['heat_stress_days'].min()} – {df['heat_stress_days'].max()} days/season")
    print(f"[climate] Veraison tmax   : {df['tmax_veraison'].min():.1f} – {df['tmax_veraison'].max():.1f} °C")
    print(f"[climate] Winter precip   : {df['precip_winter'].min():.0f} – {df['precip_winter'].max():.0f} mm")
    if n_warn > 0:
        warn_years = sorted(df[df["data_quality_warn"]]["year"].unique())
        print(f"[climate] WARNING: {n_warn} (year × AVA) rows have >{MISSING_DAY_WARN_THRESHOLD} missing growing-season days: years {warn_years}")
    else:
        print(f"[climate] Data quality: no (year × AVA) rows exceed {MISSING_DAY_WARN_THRESHOLD} missing days")

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\n[climate] Wrote {len(df)} rows → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print(f"\n[climate] Dry run — pass --apply to write Parquet.")

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build PRISM agroclimatic features.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write output to data/processed/features_climate.parquet.",
    )
    args = parser.parse_args()
    build_climate_features(apply=args.apply)

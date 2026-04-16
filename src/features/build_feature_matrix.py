"""Build the complete model feature matrix by joining all feature sources.

Joins:
    - features_climate.parquet  (year × AVA district) — PRISM agroclimatic features
    - features_water.parquet    (year)                — CIMIS ETo + DWR drought class
    - ssurgo_clean.parquet      (AVA district)        — soil properties

Output: data/processed/feature_matrix.parquet
    One row per (year × AVA district). All years where climate and water
    features overlap (currently 1991–2024).

Columns
-------
    year, ava_district                              — keys
    gdd, winkler_index                              — degree days (Apr–Oct)
    frost_days, heat_stress_days                    — extreme-temp counts
    precip_winter                                   — dormant-season precip (mm)
    tmax_veraison                                   — mean Jul–Aug tmax (°C)
    missing_days_growing, data_quality_warn         — data quality flags
    eto_season, eto_days, stations_used             — seasonal ETo (inches)
    drought_class, severity_score, is_dry           — DWR water year classification
    awc_r, drainagecl, claytotal_r, texcl           — SSURGO soil properties

Usage
-----
    python -m src.features.build_feature_matrix            # dry run
    python -m src.features.build_feature_matrix --apply    # write Parquet
"""

import argparse
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
CLIMATE_PATH = _ROOT / "data" / "processed" / "features_climate.parquet"
WATER_PATH = _ROOT / "data" / "processed" / "features_water.parquet"
SSURGO_PATH = _ROOT / "data" / "processed" / "ssurgo_clean.parquet"
OUTPUT_PATH = _ROOT / "data" / "processed" / "feature_matrix.parquet"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_feature_matrix(apply: bool = False) -> pd.DataFrame:
    """Join all feature sources into the complete model feature matrix.

    Args:
        apply: If True, write output to data/processed/feature_matrix.parquet.

    Returns:
        Complete feature DataFrame, one row per (year × AVA district).
    """
    # Load sources
    print(f"[matrix] Loading {CLIMATE_PATH.name} ...")
    climate = pd.read_parquet(CLIMATE_PATH)
    print(f"[matrix]   {len(climate):,} rows | {climate['year'].nunique()} years × {climate['ava_district'].nunique()} AVAs")

    print(f"[matrix] Loading {WATER_PATH.name} ...")
    water = pd.read_parquet(WATER_PATH)
    print(f"[matrix]   {len(water):,} rows | years {water['year'].min()}–{water['year'].max()}")

    print(f"[matrix] Loading {SSURGO_PATH.name} ...")
    ssurgo = pd.read_parquet(SSURGO_PATH)
    print(f"[matrix]   {len(ssurgo):,} AVA districts")

    # Join water features (year-level) onto climate (year × AVA)
    df = climate.merge(water, on="year", how="left")

    missing_water = df[df["drought_class"].isna()]["year"].unique().tolist()
    if missing_water:
        print(f"[matrix] WARNING: water features missing for years: {sorted(missing_water)}")

    # Join soil features (AVA-level)
    df = df.merge(ssurgo, on="ava_district", how="left")

    missing_ssurgo = df[df["awc_r"].isna()]["ava_district"].unique().tolist()
    if missing_ssurgo:
        print(f"[matrix] WARNING: SSURGO data missing for AVAs: {sorted(missing_ssurgo)}")

    df = df.sort_values(["year", "ava_district"]).reset_index(drop=True)

    # Summary
    print(f"\n[matrix] {len(df):,} rows | {df['year'].nunique()} years × {df['ava_district'].nunique()} AVAs")
    print(f"[matrix] Years: {df['year'].min()}–{df['year'].max()}")
    print(f"[matrix] AVA districts: {sorted(df['ava_district'].unique())}")
    print(f"[matrix] Columns ({len(df.columns)}): {list(df.columns)}")
    print(f"[matrix] Null counts:\n{df.isnull().sum()[df.isnull().sum() > 0].to_string()}")

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\n[matrix] Wrote {len(df):,} rows → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print(f"\n[matrix] Dry run — pass --apply to write Parquet.")

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the complete model feature matrix.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write output to data/processed/feature_matrix.parquet.",
    )
    args = parser.parse_args()
    build_feature_matrix(apply=args.apply)

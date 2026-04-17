"""Build the complete model feature matrix by joining all feature sources.

Joins:
    - features_climate.parquet  (year × AVA district) — PRISM agroclimatic features
    - features_water.parquet    (year)                — CIMIS ETo + DWR drought class
    - ssurgo_clean.parquet      (AVA district)        — soil properties
    - acreage_clean.parquet     (year × variety)      — NASS bearing acres (optional)

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
    tons_crushed_*, brix_*, price_per_ton_*         — CDFA crush report by variety (District 4)

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
CLIMATE_PATH  = _ROOT / "data" / "processed" / "features_climate.parquet"
WATER_PATH    = _ROOT / "data" / "processed" / "features_water.parquet"
SSURGO_PATH   = _ROOT / "data" / "processed" / "ssurgo_clean.parquet"
ACREAGE_PATH  = _ROOT / "data" / "processed" / "acreage_clean.parquet"
CDFA_PATH     = _ROOT / "data" / "processed" / "cdfa_clean.parquet"
OUTPUT_PATH   = _ROOT / "data" / "processed" / "feature_matrix.parquet"


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

    # Join CDFA crush features (year × variety) — tons crushed, Brix, price per ton
    if CDFA_PATH.exists():
        print(f"[matrix] Loading {CDFA_PATH.name} ...")
        cdfa = pd.read_parquet(CDFA_PATH)[["year", "variety", "tons_crushed", "brix", "price_per_ton"]]
        print(f"[matrix]   {len(cdfa):,} rows | years {cdfa['year'].min()}–{cdfa['year'].max()}")
        cdfa_wide = cdfa.pivot(index="year", columns="variety",
                               values=["tons_crushed", "brix", "price_per_ton"])
        cdfa_wide.columns = [
            f"{metric}_{variety.lower().replace(' ', '_')}"
            for metric, variety in cdfa_wide.columns
        ]
        cdfa_wide = cdfa_wide.reset_index()
        df = df.merge(cdfa_wide, on="year", how="left")
        missing_cdfa = df[df["tons_crushed_cabernet_sauvignon"].isna()]["year"].unique().tolist()
        if missing_cdfa:
            print(f"[matrix] WARNING: CDFA data missing for years: {sorted(missing_cdfa)}")
    else:
        print(f"[matrix] NOTE: {CDFA_PATH.name} not found — CDFA features skipped.")

    # Join acreage features (year × variety), if available
    if ACREAGE_PATH.exists():
        print(f"[matrix] Loading {ACREAGE_PATH.name} ...")
        acreage = pd.read_parquet(ACREAGE_PATH)[["year", "variety", "bearing_acres"]]
        print(f"[matrix]   {len(acreage):,} rows | varieties: {sorted(acreage['variety'].unique())}")
        # Pivot to wide so each variety gets its own column (year-level join)
        acreage_wide = acreage.pivot(index="year", columns="variety", values="bearing_acres")
        acreage_wide.columns = [
            f"bearing_acres_{v.lower().replace(' ', '_')}"
            for v in acreage_wide.columns
        ]
        acreage_wide = acreage_wide.reset_index()
        df = df.merge(acreage_wide, on="year", how="left")
        missing_acreage = df[df["bearing_acres_cabernet_sauvignon"].isna()]["year"].unique().tolist()
        if missing_acreage:
            print(f"[matrix] WARNING: acreage missing for years: {sorted(missing_acreage)}")
    else:
        print(f"[matrix] NOTE: {ACREAGE_PATH.name} not found — acreage features skipped.")

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

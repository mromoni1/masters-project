"""Clean raw NASS acreage data into a model-ready feature.

Reads data/raw/nass/acreage_raw.csv (written by ingest_nass_acreage.py)
and produces data/processed/acreage_clean.parquet with:

    year           int   — harvest calendar year
    variety        str   — "Cabernet Sauvignon" / "Pinot Noir" / "Chardonnay"
    bearing_acres  float — Napa County bearing acreage (or CA state-level if
                           county data suppressed)
    geo_level      str   — "county" or "state" (provenance flag)

NASS publishes the Grape Acreage Report biennially (odd years only through
the 1990s, then annually). Missing even years are forward-filled from the
prior odd year so the feature matrix has complete annual coverage.

Usage
-----
    python -m src.ingestion.clean_nass_acreage            # dry run
    python -m src.ingestion.clean_nass_acreage --apply    # write Parquet
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
RAW_PATH    = _ROOT / "data" / "raw" / "nass" / "acreage_raw.csv"
OUTPUT_PATH = _ROOT / "data" / "processed" / "acreage_clean.parquet"

VARIETIES = ["Cabernet Sauvignon", "Pinot Noir", "Chardonnay"]
START_YEAR = 1991
END_YEAR   = 2025


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

def clean_acreage(apply: bool = False) -> pd.DataFrame:
    """Clean raw NASS acreage CSV into a complete annual series.

    Steps:
    1. Load raw CSV.
    2. Filter to the three model varieties and the model year range.
    3. Reindex each variety to a full annual range (START_YEAR–END_YEAR).
    4. Forward-fill bearing_acres for missing years (biennial report gaps).
    5. Flag any remaining NaN rows as warnings.

    Args:
        apply: If True, write to data/processed/acreage_clean.parquet.

    Returns:
        Cleaned DataFrame with columns: year, variety, bearing_acres, geo_level.
    """
    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_PATH} not found.\n"
            "Run `python -m src.ingestion.ingest_nass_acreage --apply` first."
        )

    df = pd.read_csv(RAW_PATH)
    print(f"[acreage] Loaded {len(df)} rows from {RAW_PATH.name}")

    # Filter to model varieties and year range
    df = df[df["variety"].isin(VARIETIES)].copy()
    df = df[(df["year"] >= START_YEAR) & (df["year"] <= END_YEAR)]
    print(f"[acreage] After filtering: {len(df)} rows")

    # Build complete annual series per variety
    full_years = pd.DataFrame(
        [(v, y) for v in VARIETIES for y in range(START_YEAR, END_YEAR + 1)],
        columns=["variety", "year"],
    )
    df = full_years.merge(df, on=["variety", "year"], how="left")
    df = df.sort_values(["variety", "year"]).reset_index(drop=True)

    # Forward-fill within each variety (NASS biennial gaps)
    df["bearing_acres"] = df.groupby("variety")["bearing_acres"].transform(
        lambda s: s.ffill()
    )
    df["geo_level"] = df.groupby("variety")["geo_level"].transform(
        lambda s: s.ffill()
    )

    # Warn about remaining NaN (pre-series gaps)
    nulls = df[df["bearing_acres"].isna()]
    if not nulls.empty:
        print(
            f"[acreage] WARNING: {len(nulls)} rows still null after forward-fill:\n"
            + nulls[["variety", "year"]].to_string(index=False)
        )

    print(f"\n[acreage] Final: {len(df)} rows | varieties: {sorted(df['variety'].unique())}")
    print(df.groupby("variety")[["year", "bearing_acres"]].agg(
        min_year=("year", "min"),
        max_year=("year", "max"),
        min_acres=("bearing_acres", "min"),
        max_acres=("bearing_acres", "max"),
        null_count=("bearing_acres", lambda x: x.isna().sum()),
    ).to_string())

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\n[acreage] Wrote {len(df)} rows → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print("\n[acreage] Dry run — pass --apply to write Parquet.")

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean NASS acreage data.")
    parser.add_argument("--apply", action="store_true", help="Write output Parquet.")
    args = parser.parse_args()
    clean_acreage(apply=args.apply)

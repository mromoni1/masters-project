"""Build CIMIS and water stress features for the model feature matrix.

Computes seasonal ETo and joins DWR water year classification. Output is
one row per calendar year (1991–2024), representing the growing season
water stress context for that harvest year.

ETo calculation
---------------
Growing season window: Apr 1 – Oct 31 (inclusive).
When both stations (77 Oakville, 109 Carneros) have valid ETo for a day,
the two-station mean is used before summing. When only one station is
available (station 77 for 1991–1992 and 2023–2024), that station's value
is used directly. Days where ETo is NaN after imputation are excluded from
the seasonal sum; they are not treated as zero.

Station 109 (Carneros) has data from 1993-03-11 through 2022-09-13.
For 1991–1992 and 2023–2024 only station 77 is available; this is
noted in the `stations_used` column of the output.

DWR join
--------
DWR water_year N runs Oct 1 of year (N-1) through Sep 30 of year N.
For the harvest year N growing season (Apr 1 – Oct 31 of year N), the
relevant DWR classification is water_year N — it captures the preceding
winter rainfall that sets soil moisture going into budbreak.

Output
------
data/processed/features_water.parquet
    One row per year. Columns:
        year            : int   – calendar / harvest year
        eto_season      : float – cumulative growing-season ETo (inches), Apr–Oct
        eto_days        : int   – number of valid ETo days included in the sum
        stations_used   : str   – 'both', '77_only', or '109_only'
        drought_class   : str   – DWR water year classification (W/AN/BN/D/C)
        severity_score  : int   – ordinal 1–5 (1=Critical, 5=Wet)
        is_dry          : bool  – True for D or C years

Usage
-----
    python -m src.features.build_water_features            # dry run
    python -m src.features.build_water_features --apply    # write Parquet
"""

import argparse
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
CIMIS_CLEAN = _ROOT / "data" / "processed" / "cimis_clean.parquet"
DWR_CLEAN = _ROOT / "data" / "processed" / "dwr_clean.parquet"
OUTPUT_PATH = _ROOT / "data" / "processed" / "features_water.parquet"

# Growing season: Apr 1 – Oct 31 (months 4–10 inclusive)
SEASON_MONTHS = frozenset(range(4, 11))

START_YEAR = 1991
END_YEAR = 2024


# ---------------------------------------------------------------------------
# ETo seasonal aggregation
# ---------------------------------------------------------------------------

def compute_seasonal_eto(cimis: pd.DataFrame) -> pd.DataFrame:
    """Aggregate CIMIS ETo to one growing-season total per year.

    For each calendar day, computes the mean ETo across all stations that
    have a valid (non-NaN) reading. Then sums the daily means over Apr–Oct
    for each year.

    Args:
        cimis: Cleaned CIMIS DataFrame with columns: date, station_id, eto,
               eto_missing.

    Returns:
        DataFrame with columns: year, eto_season, eto_days, stations_used.
    """
    df = cimis.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    # Filter to growing season and valid ETo only
    df = df[df["month"].isin(SEASON_MONTHS) & df["eto"].notna()].copy()

    # Daily mean across available stations
    daily = (
        df.groupby(["year", "date"])
        .agg(
            eto_mean=("eto", "mean"),
            n_stations=("station_id", "nunique"),
            has_77=("station_id", lambda s: "77" in s.values),
            has_109=("station_id", lambda s: "109" in s.values),
        )
        .reset_index()
    )

    # Seasonal sum per year
    records = []
    for year, grp in daily.groupby("year"):
        eto_season = grp["eto_mean"].sum()
        eto_days = len(grp)
        both = grp["has_77"].all() and grp["has_109"].any()
        only_77 = grp["has_77"].all() and not grp["has_109"].any()
        stations_used = "both" if both else ("77_only" if only_77 else "109_only")
        records.append(
            {
                "year": year,
                "eto_season": round(eto_season, 3),
                "eto_days": eto_days,
                "stations_used": stations_used,
            }
        )

    return pd.DataFrame(records).sort_values("year").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_water_features(apply: bool = False) -> pd.DataFrame:
    """Compute seasonal ETo and join DWR classifications.

    Args:
        apply: If True, write output to data/processed/features_water.parquet.

    Returns:
        Completed feature DataFrame, one row per year.
    """
    print(f"[water] Loading CIMIS from {CIMIS_CLEAN.name} ...")
    cimis = pd.read_parquet(CIMIS_CLEAN)
    print(f"[water] {len(cimis):,} CIMIS rows | stations: {sorted(cimis['station_id'].unique())}")

    print(f"[water] Loading DWR from {DWR_CLEAN.name} ...")
    dwr = pd.read_parquet(DWR_CLEAN)
    dwr = dwr.rename(columns={"water_year": "year", "classification": "drought_class"})

    print("[water] Computing seasonal ETo (Apr–Oct) ...")
    eto = compute_seasonal_eto(cimis)

    # Filter to analysis window
    eto = eto[(eto["year"] >= START_YEAR) & (eto["year"] <= END_YEAR)]

    # Join DWR
    df = eto.merge(
        dwr[["year", "drought_class", "severity_score", "is_dry"]],
        on="year",
        how="left",
    )

    # Warn about any years missing DWR data
    missing_dwr = df[df["drought_class"].isna()]["year"].tolist()
    if missing_dwr:
        print(f"[water] WARNING: DWR classification missing for years: {missing_dwr}")

    # Summary
    print(f"\n[water] {len(df)} rows | years {df['year'].min()}–{df['year'].max()}")
    print(f"[water] ETo range: {df['eto_season'].min():.2f} – {df['eto_season'].max():.2f} inches/season")
    print(f"[water] Stations: {df['stations_used'].value_counts().to_dict()}")
    print(f"[water] Drought class counts: {df['drought_class'].value_counts().sort_index().to_dict()}")
    print(f"\n{df.to_string(index=False)}")

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\n[water] Wrote {len(df)} rows → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print(f"\n[water] Dry run — pass --apply to write Parquet.")

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build CIMIS and water stress features.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write output to data/processed/features_water.parquet.",
    )
    args = parser.parse_args()
    build_water_features(apply=args.apply)

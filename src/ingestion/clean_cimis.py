"""Clean and validate raw CIMIS daily station data for Napa County.

Reads the per-year CSV files produced by ingest_cimis.py from
data/raw/cimis/station_<id>_<year>.csv, applies range-based QC, imputes
missing ETo values, cross-validates air temperatures against PRISM where
available, and writes a cleaned daily record to
data/processed/cimis_clean.parquet.

Notes on Spatial CIMIS
----------------------
CIMIS offers a gridded Spatial CIMIS ETo product at 2 km resolution, but
that dataset is only available from approximately 2003 onwards. For records
prior to 2003 — and for all station-level analysis — this script uses the
individual station records directly. The Spatial CIMIS product is not
ingested or referenced here.

Imputation Strategy
-------------------
Only station 77 (Oakville) data is currently available. When multiple
stations are present, missing ETo for a given day is imputed as the median
ETo across all active stations on that day (spatial median imputation).
When only one station is available — as is currently the case — spatial
imputation is not possible. In that case, missing ETo is imputed via linear
interpolation over time (up to a 7-day gap), flagged with
``eto_imputed=True``. Gaps longer than 7 consecutive days remain NaN and are
documented in the missing-day summary printed at runtime.

PRISM Cross-Validation
----------------------
When data/processed/prism_clean.parquet is present, CIMIS station air
temperatures (tx, tn, in °F) are compared against the nearest PRISM
tmax/tmin values (in °C) for the same date. CIMIS values are converted to °C
before comparison. Divergences greater than 3 °C are flagged in the column
``prism_temp_flag`` but the records are not removed.

Temperature units: CIMIS API returns tx and tn in °F.
ETo units: inches/day.
Solar radiation (rs): Langleys/day.
Relative humidity (rh): percent.

Usage
-----
    python -m src.ingestion.clean_cimis            # dry run
    python -m src.ingestion.clean_cimis --apply    # write Parquet
"""

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CIMIS_DIR = DATA_RAW_DIR / "cimis"
DATA_PROCESSED_DIR = DATA_RAW_DIR.parent / "processed"
OUTPUT_PATH = DATA_PROCESSED_DIR / "cimis_clean.parquet"
PRISM_CLEAN_PATH = DATA_PROCESSED_DIR / "prism_clean.parquet"

# Physical plausibility bounds (Napa Valley climate context)
BOUNDS: dict[str, tuple[float, float]] = {
    "eto": (0.0, 0.35),      # inches/day — record daily ETo for CA is ~0.55; 0.35 is generous for Napa
    "tx":  (20.0, 120.0),    # °F — historical Napa range
    "tn":  (10.0, 90.0),     # °F
    "rs":  (0.0, 1000.0),    # Langleys/day — max observed at surface is ~1000 Ly/d
    "rh":  (1.0, 100.0),     # percent
}

# Maximum consecutive-day gap that linear interpolation will fill
MAX_INTERP_DAYS = 7

# PRISM cross-validation threshold (degrees Celsius)
PRISM_TEMP_THRESHOLD_C = 3.0

# Station Oakville / Carneros (only 77 is currently downloaded)
EXPECTED_STATIONS = ["77", "109"]

START_YEAR = 1991


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_raw_cimis() -> pd.DataFrame:
    """Concatenate all per-year CIMIS CSVs into a single DataFrame.

    Files are expected at data/raw/cimis/station_<id>_<year>.csv with
    columns: date, station_id, eto, tx, tn, rs, rh.

    Returns:
        Combined raw DataFrame sorted by (station_id, date).
    """
    files = sorted(CIMIS_DIR.glob("station_*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No CIMIS CSV files found in {CIMIS_DIR}. "
            "Run ingest_cimis.py first."
        )

    dfs = []
    for f in files:
        df = pd.read_csv(f, parse_dates=["date"])
        df["station_id"] = df["station_id"].astype(str)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.sort_values(["station_id", "date"]).reset_index(drop=True)

    stations_found = sorted(combined["station_id"].unique())
    print(f"Loaded {len(files)} file(s) | stations: {stations_found}")

    missing_stations = [s for s in EXPECTED_STATIONS if s not in stations_found]
    if missing_stations:
        print(
            f"  [NOTE] Station(s) {missing_stations} not yet downloaded. "
            "Spatial imputation will fall back to temporal interpolation."
        )

    return combined


# ---------------------------------------------------------------------------
# Range QC
# ---------------------------------------------------------------------------

def apply_range_qc(df: pd.DataFrame) -> pd.DataFrame:
    """Replace out-of-range values with NaN and record which cells were flagged.

    Values outside BOUNDS for each variable are set to NaN. A boolean column
    ``<var>_range_flag`` is added for each variable that had any out-of-range
    values, recording which rows were affected before replacement.

    Args:
        df: Raw combined DataFrame.

    Returns:
        DataFrame with out-of-range values replaced by NaN and flag columns added.
    """
    df = df.copy()
    total_flagged = 0
    for var, (lo, hi) in BOUNDS.items():
        if var not in df.columns:
            continue
        mask = df[var].notna() & ((df[var] < lo) | (df[var] > hi))
        n = mask.sum()
        if n > 0:
            df[f"{var}_range_flag"] = mask
            df.loc[mask, var] = np.nan
            print(f"  Range QC: {var} — {n} value(s) out of [{lo}, {hi}] set to NaN")
            total_flagged += n
        else:
            df[f"{var}_range_flag"] = False

    if total_flagged == 0:
        print("  Range QC: no out-of-range values found")

    return df


# ---------------------------------------------------------------------------
# Missing-day detection
# ---------------------------------------------------------------------------

def find_missing_days(df: pd.DataFrame) -> dict[str, list[date]]:
    """Return missing dates per station across the full expected date range.

    Args:
        df: DataFrame with columns date and station_id.

    Returns:
        Dict mapping station_id → sorted list of missing dates.
    """
    all_dates = pd.date_range(
        start=f"{START_YEAR}-01-01",
        end=df["date"].max(),
        freq="D",
    )
    missing: dict[str, list[date]] = {}
    for station, grp in df.groupby("station_id"):
        present = set(grp["date"].dt.date)
        gaps = [d.date() for d in all_dates if d.date() not in present]
        missing[str(station)] = gaps

    return missing


# ---------------------------------------------------------------------------
# ETo gap identification and imputation
# ---------------------------------------------------------------------------

def flag_and_impute_eto(df: pd.DataFrame) -> pd.DataFrame:
    """Flag missing ETo values and impute them where possible.

    Imputation order:
        1. If multiple stations are active on the same day, use the spatial
           median of those stations' ETo values.
        2. If only one station is available (current situation with only
           station 77), use linear interpolation over time for gaps of
           up to MAX_INTERP_DAYS consecutive missing days.
        3. Gaps longer than MAX_INTERP_DAYS remain NaN.

    Adds column ``eto_imputed`` (bool): True when ETo was originally NaN
    and a value was filled in.

    Args:
        df: DataFrame after range QC.

    Returns:
        DataFrame with ETo imputed where possible and eto_imputed flag added.
    """
    df = df.copy()
    df["eto_missing"] = df["eto"].isna()

    stations = df["station_id"].unique()

    if len(stations) > 1:
        # Spatial median across active stations for each date
        daily_median = (
            df.groupby("date")["eto"]
            .median()
            .rename("eto_spatial_median")
        )
        df = df.merge(daily_median, on="date", how="left")
        fill_mask = df["eto"].isna() & df["eto_spatial_median"].notna()
        df.loc[fill_mask, "eto"] = df.loc[fill_mask, "eto_spatial_median"]
        df["eto_imputed"] = fill_mask
        df.drop(columns=["eto_spatial_median"], inplace=True)
        n_imputed = fill_mask.sum()
        print(f"  ETo imputation: {n_imputed} values filled via spatial median")
    else:
        # Temporal linear interpolation per station, limited to MAX_INTERP_DAYS
        imputed_flag = pd.Series(False, index=df.index)
        for station, grp in df.groupby("station_id"):
            idx = grp.index
            eto_before = df.loc[idx, "eto"].copy()
            df.loc[idx, "eto"] = (
                df.loc[idx, "eto"]
                .interpolate(method="linear", limit=MAX_INTERP_DAYS, limit_direction="both")
            )
            newly_filled = df.loc[idx, "eto"].notna() & eto_before.isna()
            imputed_flag.loc[idx[newly_filled]] = True

        df["eto_imputed"] = imputed_flag
        n_imputed = imputed_flag.sum()
        n_remain = df["eto"].isna().sum()
        print(
            f"  ETo imputation: {n_imputed} values filled via linear interpolation "
            f"(≤{MAX_INTERP_DAYS}-day gaps) | {n_remain} values remain NaN"
        )

    return df


# ---------------------------------------------------------------------------
# PRISM cross-validation
# ---------------------------------------------------------------------------

def cross_validate_prism(df: pd.DataFrame) -> pd.DataFrame:
    """Flag CIMIS temperature records that diverge from PRISM by > 3 °C.

    Loads data/processed/prism_clean.parquet, converts CIMIS tx/tn from °F
    to °C, and compares against PRISM tmax/tmin for the same date. The
    comparison uses the "Napa Valley" district (or the first available
    district when the AVA file has been loaded) as the PRISM reference.

    Adds column ``prism_temp_flag`` (bool): True when |CIMIS_temp_C -
    PRISM_temp_C| > PRISM_TEMP_THRESHOLD_C for either tx or tn.

    If prism_clean.parquet is not yet available, the column is added as
    all-False and a notice is printed.

    Args:
        df: DataFrame with tx, tn columns (in °F).

    Returns:
        DataFrame with prism_temp_flag column added.
    """
    df = df.copy()

    if not PRISM_CLEAN_PATH.exists():
        print(
            f"  PRISM cross-validation: skipped — {PRISM_CLEAN_PATH} not found. "
            "Run clean_prism.py after ingesting PRISM rasters to enable this check."
        )
        df["prism_temp_flag"] = False
        return df

    prism = pd.read_parquet(PRISM_CLEAN_PATH, columns=["date", "ava_district", "tmax", "tmin"])
    prism["date"] = pd.to_datetime(prism["date"])

    # Use the first district as the spatial reference (Napa Valley or nearest sub-AVA)
    ref_district = prism["ava_district"].iloc[0]
    prism_ref = prism[prism["ava_district"] == ref_district][["date", "tmax", "tmin"]].copy()
    prism_ref = prism_ref.rename(columns={"tmax": "prism_tmax_c", "tmin": "prism_tmin_c"})

    df = df.merge(prism_ref, on="date", how="left")

    # Convert CIMIS °F → °C
    tx_c = (df["tx"] - 32) * 5 / 9
    tn_c = (df["tn"] - 32) * 5 / 9

    flag = (
        (df["prism_tmax_c"].notna() & tx_c.notna() & ((tx_c - df["prism_tmax_c"]).abs() > PRISM_TEMP_THRESHOLD_C))
        | (df["prism_tmin_c"].notna() & tn_c.notna() & ((tn_c - df["prism_tmin_c"]).abs() > PRISM_TEMP_THRESHOLD_C))
    )
    df["prism_temp_flag"] = flag
    df.drop(columns=["prism_tmax_c", "prism_tmin_c"], inplace=True)

    n_flagged = flag.sum()
    print(
        f"  PRISM cross-validation: {n_flagged} record(s) flagged "
        f"(|ΔT| > {PRISM_TEMP_THRESHOLD_C}°C vs {ref_district})"
    )
    return df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def clean_cimis(apply: bool = False) -> pd.DataFrame:
    """Build and optionally save the cleaned CIMIS daily dataset.

    Steps:
        1. Load all raw per-year CSVs.
        2. Apply range-based QC (replace outliers with NaN, add flag columns).
        3. Identify missing station-days.
        4. Impute missing ETo values (spatial median if multiple stations,
           else temporal linear interpolation up to 7 days).
        5. Cross-validate temperatures against PRISM (if available).
        6. Print summary via log_load_summary.
        7. Optionally write Parquet to data/processed/.

    Args:
        apply: If True, write Parquet output. Otherwise prints a dry-run summary.

    Returns:
        Cleaned DataFrame with columns:
            date, station_id, eto, tx, tn, rs, rh,
            eto_missing, eto_imputed, prism_temp_flag,
            and per-variable _range_flag columns.
    """
    # Step 1 — load
    df = load_raw_cimis()

    # Step 2 — range QC
    print("\nApplying range QC...")
    df = apply_range_qc(df)

    # Step 3 — missing days
    print("\nChecking for missing station-days...")
    missing = find_missing_days(df)
    for station, gaps in missing.items():
        print(f"  Station {station}: {len(gaps)} missing day(s)", end="")
        if gaps:
            print(f" | first gap: {gaps[0]}, last gap: {gaps[-1]}")
        else:
            print()

    # Step 4 — ETo imputation
    print("\nImputing missing ETo values...")
    df = flag_and_impute_eto(df)

    # Step 5 — PRISM cross-validation
    print("\nCross-validating temperatures against PRISM...")
    df = cross_validate_prism(df)

    # Step 6 — summary
    print()
    log_load_summary(df, "CIMIS-clean")
    n_eto_missing = df["eto_missing"].sum()
    n_eto_imputed = df["eto_imputed"].sum()
    n_prism_flag = df["prism_temp_flag"].sum()
    print(f"  ETo originally missing: {n_eto_missing}")
    print(f"  ETo imputed:            {n_eto_imputed}")
    print(f"  PRISM temp flags:       {n_prism_flag}")

    # Step 7 — write
    if apply:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\nSaved → {OUTPUT_PATH}")
    else:
        print(f"\n[Dry run] Would write {len(df):,} rows to {OUTPUT_PATH}")
        print("Re-run with --apply to write the Parquet file.")

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean and validate raw CIMIS daily station data for Napa County."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write cleaned Parquet output to data/processed/cimis_clean.parquet.",
    )
    args = parser.parse_args()
    clean_cimis(apply=args.apply)


if __name__ == "__main__":
    main()

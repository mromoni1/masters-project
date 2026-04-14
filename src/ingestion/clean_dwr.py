"""Clean and normalize DWR Sacramento Valley water year classifications.

Reads the raw CSV produced by ingest_dwr.py, filters to the project's
analysis window (1991–2025), adds derived columns for water year boundaries
and a numeric severity score, and writes the result to Parquet.

Water year convention:
  Water year N runs Oct 1 of year (N-1) through Sep 30 of year N.
  e.g. water_year=2024 → wy_start=2023-10-01, wy_end=2024-09-30

Classification codes (Sacramento Valley):
  W  = Wet          (score 5)
  AN = Above Normal (score 4)
  BN = Below Normal (score 3)
  D  = Dry          (score 2)
  C  = Critical     (score 1)

Output
------
data/processed/dwr_clean.parquet
    One row per water year. Columns:
        water_year      : int   – water year (year in which Sep 30 falls)
        classification  : str   – Sacramento Valley year type (W/AN/BN/D/C)
        severity_score  : int   – ordinal 1–5 (1=driest, 5=wettest)
        is_dry          : bool  – True for D or C years
        wy_start        : date  – Oct 1 of (water_year - 1)
        wy_end          : date  – Sep 30 of water_year

Usage
-----
    python -m src.ingestion.clean_dwr            # preview (dry run)
    python -m src.ingestion.clean_dwr --apply    # write Parquet
"""

import argparse
from pathlib import Path

import pandas as pd

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DWR_DIR = DATA_RAW_DIR / "dwr"
RAW_FILE = DWR_DIR / "dwr_water_year_classifications.csv"
DATA_PROCESSED_DIR = DATA_RAW_DIR.parent / "processed"
OUTPUT_FILE = DATA_PROCESSED_DIR / "dwr_clean.parquet"

START_YEAR = 1991
END_YEAR = 2025

# Ordinal severity: higher = wetter
SEVERITY_MAP: dict[str, int] = {
    "W": 5,
    "AN": 4,
    "BN": 3,
    "D": 2,
    "C": 1,
}


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_raw(path: Path) -> pd.DataFrame:
    """Read the raw DWR CSV and validate its structure.

    Args:
        path: Path to dwr_water_year_classifications.csv.

    Returns:
        DataFrame with columns: water_year (int), classification (str).

    Raises:
        FileNotFoundError: If the raw CSV does not exist.
        ValueError: If expected columns are missing.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Raw DWR file not found at {path}. "
            "Run src/ingestion/ingest_dwr.py first."
        )

    df = pd.read_csv(path, dtype={"water_year": int, "classification": str})

    required = {"water_year", "classification"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Raw DWR CSV is missing columns: {missing}")

    return df[["water_year", "classification"]].copy()


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------

def clean(df: pd.DataFrame, start_year: int = START_YEAR, end_year: int = END_YEAR) -> pd.DataFrame:
    """Filter, validate, and enrich the raw DWR classifications.

    Args:
        df: Raw DataFrame with water_year and classification columns.
        start_year: First water year to include (inclusive).
        end_year: Last water year to include (inclusive).

    Returns:
        Cleaned DataFrame with one row per water year.
    """
    # Filter to analysis window
    df = df[(df["water_year"] >= start_year) & (df["water_year"] <= end_year)].copy()

    # Validate classifications
    unknown = set(df["classification"]) - set(SEVERITY_MAP)
    if unknown:
        raise ValueError(f"Unexpected classification codes: {unknown}")

    # Check for gaps in the year sequence
    expected = set(range(start_year, end_year + 1))
    found = set(df["water_year"])
    missing_years = sorted(expected - found)
    if missing_years:
        print(f"[DWR] Warning: {len(missing_years)} water year(s) missing from raw data: {missing_years}")

    # Derived columns
    df["severity_score"] = df["classification"].map(SEVERITY_MAP).astype(int)
    df["is_dry"] = df["classification"].isin({"D", "C"})

    # Water year boundary dates
    # wy_start = Oct 1 of (water_year - 1)
    # wy_end   = Sep 30 of water_year
    df["wy_start"] = pd.to_datetime(
        (df["water_year"] - 1).astype(str) + "-10-01"
    ).dt.date
    df["wy_end"] = pd.to_datetime(
        df["water_year"].astype(str) + "-09-30"
    ).dt.date

    df = df.sort_values("water_year").reset_index(drop=True)

    return df[["water_year", "classification", "severity_score", "is_dry", "wy_start", "wy_end"]]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def clean_dwr(apply: bool = False) -> pd.DataFrame | None:
    """Load, clean, and optionally write DWR water year classifications.

    Args:
        apply: If True, write the cleaned DataFrame to Parquet.

    Returns:
        Cleaned DataFrame, or None if an error occurred.
    """
    print(f"[DWR] Reading raw CSV from {RAW_FILE} ...")
    df_raw = load_raw(RAW_FILE)
    print(f"[DWR] Raw rows: {len(df_raw):,} (water years {df_raw['water_year'].min()}–{df_raw['water_year'].max()})")

    df = clean(df_raw)

    log_load_summary(df, "DWR")
    print(f"[DWR] Water years: {df['water_year'].min()}–{df['water_year'].max()}")
    print(f"[DWR] Classification counts:\n{df['classification'].value_counts().sort_index().to_string()}")
    print(f"[DWR] Dry years (D/C): {df['is_dry'].sum()} of {len(df)}")
    print(f"\n{df.to_string(index=False)}")

    if apply:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_FILE, index=False)
        print(f"\n[DWR] Wrote {len(df)} rows → {OUTPUT_FILE}")
    else:
        print("\n[DWR] Dry run — pass --apply to write Parquet.")

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean DWR water year classifications.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write cleaned output to data/processed/dwr_clean.parquet.",
    )
    args = parser.parse_args()
    clean_dwr(apply=args.apply)

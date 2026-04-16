"""Clean and validate DWR Sacramento Valley water year classifications.

Reads the raw CSV produced by ingest_dwr.py, validates classifications,
adds an ordinal severity score and a boolean drought flag, and writes
the result to data/processed/dwr_clean.parquet.

Severity scoring
----------------
The five Sacramento Valley year types are mapped to an ordinal 1–5 scale
reflecting agricultural stress, from most to least severe:

    C  (Critical)      → 1
    D  (Dry)           → 2
    BN (Below Normal)  → 3
    AN (Above Normal)  → 4
    W  (Wet)           → 5

is_dry is True for D and C years — conditions associated with meaningful
water allocation reductions and above-average irrigation demand in Napa.

Output
------
data/processed/dwr_clean.parquet
    One row per water year. Columns:
        water_year      : int  – water year (Oct of prior calendar year – Sep)
        classification  : str  – Sacramento Valley year type: W / AN / BN / D / C
        calendar_year   : int  – calendar year in which water year ends (= water_year)
        severity_score  : int  – ordinal 1–5 (1=Critical, 5=Wet)
        is_dry          : bool – True for D or C years

Usage
-----
    python -m src.ingestion.clean_dwr            # dry run
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

INPUT_FILE = DATA_RAW_DIR / "dwr" / "dwr_water_year_classifications.csv"
DATA_PROCESSED_DIR = DATA_RAW_DIR.parent / "processed"
OUTPUT_PATH = DATA_PROCESSED_DIR / "dwr_clean.parquet"

VALID_CLASSIFICATIONS = {"W", "AN", "BN", "D", "C"}

SEVERITY_SCORES: dict[str, int] = {
    "C":  1,
    "D":  2,
    "BN": 3,
    "AN": 4,
    "W":  5,
}

DRY_CLASSIFICATIONS = {"D", "C"}


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_raw_dwr() -> pd.DataFrame:
    """Load the raw DWR water year classification CSV.

    Returns:
        DataFrame with columns: water_year (int), classification (str),
        calendar_year (int).

    Raises:
        FileNotFoundError: If the raw CSV is not present.
    """
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Raw DWR file not found: {INPUT_FILE}\n"
            "Run ingest_dwr.py first."
        )

    df = pd.read_csv(INPUT_FILE)
    df["water_year"] = df["water_year"].astype(int)
    df["calendar_year"] = df["calendar_year"].astype(int)
    df["classification"] = df["classification"].str.strip().str.upper()

    print(f"[DWR] Loaded {len(df):,} rows from {INPUT_FILE.name}")
    print(f"[DWR] Water year range: {df['water_year'].min()} – {df['water_year'].max()}")
    return df


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_classifications(df: pd.DataFrame) -> pd.DataFrame:
    """Check for unexpected classification values and duplicate water years.

    Args:
        df: Raw DWR DataFrame.

    Returns:
        Validated DataFrame (unchanged if no issues found).

    Raises:
        ValueError: If duplicate water years are present.
    """
    unknown = df[~df["classification"].isin(VALID_CLASSIFICATIONS)]
    if not unknown.empty:
        print(
            f"[DWR] WARNING: {len(unknown)} row(s) with unrecognised classification "
            f"values: {sorted(unknown['classification'].unique())} — these rows will "
            "have NaN severity_score and is_dry=False."
        )

    dupes = df[df.duplicated(subset="water_year", keep=False)]
    if not dupes.empty:
        raise ValueError(
            f"Duplicate water years found: {sorted(dupes['water_year'].unique())}. "
            "Check the raw CSV."
        )

    return df


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add severity_score and is_dry columns.

    Args:
        df: Validated DWR DataFrame.

    Returns:
        DataFrame with severity_score (int) and is_dry (bool) added.
    """
    df = df.copy()
    df["severity_score"] = df["classification"].map(SEVERITY_SCORES)
    df["is_dry"] = df["classification"].isin(DRY_CLASSIFICATIONS)
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def clean_dwr(apply: bool = False) -> pd.DataFrame:
    """Load, validate, enrich, and optionally save DWR classifications.

    Args:
        apply: If True, write output to data/processed/dwr_clean.parquet.

    Returns:
        Cleaned DataFrame with columns: water_year, classification,
        calendar_year, severity_score, is_dry.
    """
    df = load_raw_dwr()

    print("[DWR] Validating classifications...")
    df = validate_classifications(df)

    print("[DWR] Adding severity_score and is_dry...")
    df = add_derived_columns(df)

    df = df.sort_values("water_year").reset_index(drop=True)

    # Summary
    print(f"\n[DWR] Classification counts:")
    for cls in ["W", "AN", "BN", "D", "C"]:
        n = (df["classification"] == cls).sum()
        label = {"W": "Wet", "AN": "Above Normal", "BN": "Below Normal",
                 "D": "Dry", "C": "Critical"}[cls]
        print(f"       {cls:2s} ({label:<13}) score={SEVERITY_SCORES[cls]}  n={n}")
    print(f"\n[DWR] Dry years (D or C): {df['is_dry'].sum()}")
    log_load_summary(df, "DWR-clean")

    if apply:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\n[DWR] Wrote {len(df)} rows → {OUTPUT_PATH.relative_to(DATA_RAW_DIR.parents[1])}")
    else:
        print(f"\n[DWR] Dry run — pass --apply to write Parquet.")

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean and validate DWR water year classifications."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write cleaned Parquet output to data/processed/dwr_clean.parquet.",
    )
    args = parser.parse_args()
    clean_dwr(apply=args.apply)
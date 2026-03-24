"""Shared utilities for ingestion scripts."""

from pathlib import Path

import pandas as pd


DATA_RAW_DIR = Path(__file__).parents[2] / "data" / "raw"


def log_load_summary(df: pd.DataFrame, source_name: str) -> None:
    """Print row count and date range to stdout after loading a dataset.

    Looks for a column named 'date' (case-insensitive) to derive the date range.
    If no date column is found, only the row count is printed.

    Args:
        df: The loaded DataFrame.
        source_name: Human-readable name for the data source (e.g. 'PRISM', 'CIMIS').
    """
    date_col = next(
        (col for col in df.columns if col.lower() == "date"),
        None,
    )

    if date_col is not None:
        min_date = df[date_col].min()
        max_date = df[date_col].max()
        print(
            f"[{source_name}] loaded {len(df):,} rows | "
            f"date range: {min_date} – {max_date}"
        )
    else:
        print(f"[{source_name}] loaded {len(df):,} rows | no date column found")


def ensure_raw_dir(source: str) -> Path:
    """Create and return the data/raw/<source>/ directory.

    Args:
        source: Data source subdirectory name (e.g. 'prism', 'cimis').

    Returns:
        Path to the created (or already existing) directory.
    """
    path = DATA_RAW_DIR / source
    path.mkdir(parents=True, exist_ok=True)
    return path

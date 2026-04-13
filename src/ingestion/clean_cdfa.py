"""Parse and clean CDFA Grape Crush Report data.

Reads Table 2 (tons crushed by district), Table 3 (degrees Brix by
district), and Table 6 (weighted average price per ton by district) from
raw CDFA Excel files downloaded per year. Filters to Cabernet Sauvignon,
Pinot Noir, and Chardonnay in Napa County (CDFA Reporting District 4).

CDFA Reporting District → Napa County AVA mapping
--------------------------------------------------
District 4 = Napa County
  Encompasses all Napa Valley AVAs, including but not limited to:
    - Napa Valley (umbrella AVA)
    - Oakville, Rutherford, Stags Leap District
    - Howell Mountain, Diamond Mountain District, Spring Mountain District
    - Mount Veeder, Atlas Peak, Coombsville
    - Oak Knoll District, Yountville, St. Helena, Calistoga
    - Chiles Valley District, Wild Horse Valley
    - Los Carneros (shared with Sonoma County)
  The CDFA uses county-level reporting; there is no finer-grained
  district that corresponds 1:1 with a sub-AVA.

Output
------
data/processed/cdfa_clean.parquet
    One row per (year × variety × district). Columns:
        year             : int   – harvest year
        variety          : str   – canonical variety name
        district         : int   – CDFA reporting district number (always 4)
        tons_crushed     : float – tons crushed (Table 2, district 4)
        brix             : float – weighted avg degrees Brix at crush (Table 3);
                                   NaN when data unavailable for that cell
        price_per_ton    : float – weighted avg grower return $/ton (Table 6);
                                   NaN when data unavailable for that cell
        brix_available   : bool  – True when a valid numeric Brix reading exists

Usage
-----
    python -m src.ingestion.clean_cdfa            # preview (dry run)
    python -m src.ingestion.clean_cdfa --apply    # write Parquet
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CDFA_DIR = DATA_RAW_DIR / "cdfa"
DATA_PROCESSED_DIR = DATA_RAW_DIR.parent / "processed"

# Target varieties: canonical lowercase key → display name
TARGET_VARIETIES: dict[str, str] = {
    "cabernet sauvignon": "Cabernet Sauvignon",
    "chardonnay": "Chardonnay",
    "pinot noir": "Pinot Noir",
}

# CDFA district number for Napa County
NAPA_DISTRICT = 4

# Column index (0-based) for District 4 — consistent across all file formats
# verified across 1991–2024 (old .XLS and new .xlsx layouts).
_DISTRICT_4_COL = 4

# Sentinel strings that represent "no data" in CDFA tables
_MISSING_SENTINELS = {"--", "-", "n/a", "na", ""}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_variety(raw: str) -> Optional[str]:
    """Map a raw variety string to a canonical display name, or None.

    Strips trailing ' *' markers used in newer CDFA files and does a
    case-insensitive prefix match against TARGET_VARIETIES keys.

    Args:
        raw: Raw variety name from the Excel file (e.g. 'Pinot Noir *').

    Returns:
        Canonical display name (e.g. 'Pinot Noir') or None if not a target.
    """
    normalized = str(raw).strip().rstrip("*").strip().lower()
    for key, display in TARGET_VARIETIES.items():
        if normalized == key:
            return display
    return None


def _to_float_or_nan(val: object) -> float:
    """Convert a cell value to float, returning NaN for missing sentinels.

    Args:
        val: Raw cell value from pandas (str, float, int, or NaN).

    Returns:
        Numeric float, or float('nan') if the value signals missing data.
    """
    if pd.isna(val):
        return float("nan")
    s = str(val).strip()
    if s.lower() in _MISSING_SENTINELS:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _read_district_values(path: Path, district_col: int = _DISTRICT_4_COL) -> dict[str, float]:
    """Extract target-variety values from a single CDFA table Excel file.

    Reads the raw file without assuming a header row. Scans every row for
    variety names matching TARGET_VARIETIES and returns the value at the
    specified district column.

    Args:
        path: Path to the .xls or .xlsx file.
        district_col: 0-based column index for the target district (default: 4).

    Returns:
        Dict mapping canonical variety display name → float value (NaN if absent).
    """
    try:
        df = pd.read_excel(path, header=None, dtype=object)
    except Exception as exc:
        print(f"[CDFA] WARNING: could not read {path.name}: {exc}", file=sys.stderr)
        return {}

    result: dict[str, float] = {}
    for _, row in df.iterrows():
        variety = _normalize_variety(row.iloc[0])
        if variety is None:
            continue
        val = row.iloc[district_col] if district_col < len(row) else float("nan")
        result[variety] = _to_float_or_nan(val)

    return result


def _find_table_file(year_dir: Path, table_num: str) -> Optional[Path]:
    """Locate the best matching file for a given table number in a year directory.

    Prefers 'final' over 'prelim' and ignores web/supplement variants.

    Args:
        year_dir: Path to the year's CDFA directory (e.g. data/raw/cdfa/2023_CDFA).
        table_num: Zero-padded two-char table ID, e.g. '02', '03', '06'.

    Returns:
        Path to the matching file, or None if not found.
    """
    candidates: list[Path] = []
    for path in year_dir.iterdir():
        stem = path.stem.lower()
        # Must reference the right table and not be a web/supplement variant
        if f"tb{table_num}" not in stem and f"tb0{table_num.lstrip('0')}" not in stem:
            continue
        if "web" in stem or "supplement" in stem:
            continue
        if path.suffix.lower() not in {".xls", ".xlsx"}:
            continue
        candidates.append(path)

    if not candidates:
        return None

    # Prefer final over prelim; within same status prefer shorter (simpler) name
    def sort_key(p: Path) -> tuple[int, int]:
        is_prelim = 1 if "prelim" in p.stem.lower() else 0
        return (is_prelim, len(p.name))

    return sorted(candidates, key=sort_key)[0]


# ---------------------------------------------------------------------------
# Main cleaning logic
# ---------------------------------------------------------------------------


def clean_cdfa(apply: bool = False) -> Optional[pd.DataFrame]:
    """Parse CDFA files and produce a clean analysis-ready DataFrame.

    Iterates over all year directories under data/raw/cdfa/, reads Table 2
    (tons), Table 3 (Brix), and Table 6 (price) for Napa County (District 4),
    and combines them into a tidy long-format table.

    Args:
        apply: When True, writes the cleaned DataFrame to Parquet and prints
            a load summary. When False (default), only prints a preview.

    Returns:
        Cleaned DataFrame, or None if no data was found.
    """
    year_dirs = sorted(CDFA_DIR.glob("*_CDFA"))
    if not year_dirs:
        print(f"[CDFA] no *_CDFA directories found under {CDFA_DIR}", file=sys.stderr)
        sys.exit(1)

    records: list[dict] = []
    missing_years: list[int] = []

    for year_dir in year_dirs:
        year_match = str(year_dir.name)[:4]
        try:
            year = int(year_match)
        except ValueError:
            continue

        tb02 = _find_table_file(year_dir, "02")
        tb03 = _find_table_file(year_dir, "03")
        tb06 = _find_table_file(year_dir, "06")

        if tb02 is None:
            print(f"[CDFA] WARNING: year {year} — Table 02 not found, skipping", file=sys.stderr)
            missing_years.append(year)
            continue

        tons = _read_district_values(tb02)
        brix = _read_district_values(tb03) if tb03 is not None else {}
        price = _read_district_values(tb06) if tb06 is not None else {}

        for variety in TARGET_VARIETIES.values():
            if variety not in tons:
                continue  # variety absent from this year's report

            brix_val = brix.get(variety, float("nan"))
            brix_available = not pd.isna(brix_val) and brix_val > 0

            records.append(
                {
                    "year": year,
                    "variety": variety,
                    "district": NAPA_DISTRICT,
                    "tons_crushed": tons.get(variety, float("nan")),
                    "brix": brix_val if brix_available else float("nan"),
                    "price_per_ton": price.get(variety, float("nan")),
                    "brix_available": brix_available,
                }
            )

    if not records:
        print("[CDFA] no records extracted — check CDFA_DIR and table files", file=sys.stderr)
        return None

    df = (
        pd.DataFrame(records)
        .sort_values(["year", "variety"])
        .reset_index(drop=True)
    )

    # ------------------------------------------------------------------
    # Preview / apply
    # ------------------------------------------------------------------
    print(f"\n[CDFA] {len(df):,} rows extracted")
    print(f"       varieties : {sorted(df['variety'].unique())}")
    print(f"       year range: {df['year'].min()} – {df['year'].max()}")
    print(f"       district  : {sorted(df['district'].unique())}")
    if missing_years:
        print(f"       skipped years (missing Table 02): {missing_years}")

    preview = df.head(6).to_string(index=False)
    print(f"\nPreview:\n{preview}\n")

    if not apply:
        print("[CDFA] DRY RUN — pass --apply to write Parquet\n")
        return df

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_PROCESSED_DIR / "cdfa_clean.parquet"
    df.to_parquet(out_path, index=False)
    print(f"[CDFA] written → {out_path.relative_to(DATA_RAW_DIR.parent.parent)}")

    log_load_summary(df.rename(columns={"year": "date"}), "CDFA")

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write cleaned data to data/processed/cdfa_clean.parquet (default: dry run)",
    )
    args = parser.parse_args()
    clean_cdfa(apply=args.apply)

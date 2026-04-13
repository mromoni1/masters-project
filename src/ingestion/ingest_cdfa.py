"""Normalize and catalog CDFA Grape Crush Report Excel files.

Renames raw files in data/raw/cdfa/{year}_CDFA/ to a consistent scheme:

    {year}_gcbtb{NN}_{status}.xls[x]          — primary table file
    {year}_gcbtb{NN}_{status}_{variant}.xls[x] — web / supplement variant

where:
    NN      : zero-padded table number (tb81→08a, tb82/tb081/tb082→08a/08b)
    status  : 'final' (default) or 'prelim'
    variant : 'web', 'supplement', or 'web_supplement' (omitted when absent)

Run with no arguments for a dry-run preview, or pass --apply to rename files
and write data/raw/cdfa/manifest.csv.

Source:
    USDA NASS — California Grape Crush Reports
    https://www.nass.usda.gov/Statistics_by_State/California/Publications/Grape_Crush/
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CDFA_DIR = DATA_RAW_DIR / "cdfa"
EXCEL_SUFFIXES = {".xls", ".xlsx", ".XLS", ".XLSX"}

# Matches both gcbtb and gc_tb naming conventions
_TABLE_RE = re.compile(r"gc(?:b|_)tb(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Filename parser
# ---------------------------------------------------------------------------

def _normalize_table_num(raw: str) -> str:
    """Map raw digit string to canonical 2-char table ID.

    Args:
        raw: Digit string extracted from the filename (e.g. '08', '81', '081').

    Returns:
        Canonical table ID: '08a', '08b', or zero-padded 2-digit string.
    """
    stripped = raw.lstrip("0") or "0"
    if stripped == "81":
        return "08a"
    if stripped == "82":
        return "08b"
    return raw.zfill(2)


def _parse_variant(suffix_after_table: str) -> str:
    """Extract the variant token from the suffix that follows the table number.

    Args:
        suffix_after_table: Raw remainder of the filename stem after the table
            number digits, e.g. '_web_supplement', '-Web', 's', ''.

    Returns:
        One of 'web_supplement', 'web', 'supplement', or '' (no variant).
    """
    s = suffix_after_table.strip("_-").lower()
    if "web" in s and "supplement" in s:
        return "web_supplement"
    if "web" in s:
        return "web"
    if "supplement" in s or s == "s":
        return "supplement"
    return ""


def parse_cdfa_file(path: Path) -> dict | None:
    """Parse a CDFA Excel file into its normalized components.

    Extracts year (from the parent folder name), table number, status, and
    variant from the filename. Returns None if the file cannot be parsed as a
    recognizable CDFA table file.

    Args:
        path: Absolute path to the file.

    Returns:
        Dict with keys: year, table, status, variant, old_name, new_name,
        old_path, new_path. None if the file does not match.
    """
    if path.suffix not in EXCEL_SUFFIXES:
        return None

    # Year from parent folder ({YYYY}_CDFA)
    year_match = re.match(r"(\d{4})", path.parent.name)
    if not year_match:
        return None
    year = int(year_match.group(1))

    stem = path.stem
    m = _TABLE_RE.search(stem)
    if not m:
        return None

    raw_num = m.group(1)
    after_table = stem[m.end():]          # everything after the digit(s)

    table = _normalize_table_num(raw_num)

    stem_lower = stem.lower()
    status = "prelim" if "prelim" in stem_lower else "final"

    variant = _parse_variant(after_table)

    # Normalize extension: .XLS → .xls, .xlsx stays .xlsx
    ext = path.suffix.lower()

    if variant:
        new_name = f"{year}_gcbtb{table}_{status}_{variant}{ext}"
    else:
        new_name = f"{year}_gcbtb{table}_{status}{ext}"

    return {
        "year": year,
        "table": table,
        "status": status,
        "variant": variant,
        "old_name": path.name,
        "new_name": new_name,
        "old_path": path,
        "new_path": path.parent / new_name,
    }


# ---------------------------------------------------------------------------
# Rename + manifest
# ---------------------------------------------------------------------------

def normalize_cdfa(apply: bool = False) -> None:
    """Rename CDFA files to the canonical scheme and write a manifest CSV.

    Args:
        apply: When False (default), print the rename plan without touching
            files. When True, rename files and write manifest.csv.
    """
    year_dirs = sorted(CDFA_DIR.glob("*_CDFA"))
    if not year_dirs:
        print(f"[CDFA] no *_CDFA directories found under {CDFA_DIR}")
        sys.exit(1)

    records: list[dict] = []
    skipped: list[Path] = []
    conflicts: list[tuple[Path, Path]] = []

    for year_dir in year_dirs:
        for path in sorted(year_dir.iterdir()):
            parsed = parse_cdfa_file(path)
            if parsed is None:
                if path.name != ".DS_Store":
                    skipped.append(path)
                continue

            # Detect collisions (two source files mapping to the same target)
            existing = next(
                (r for r in records if r["new_path"] == parsed["new_path"]), None
            )
            if existing:
                conflicts.append((path, parsed["new_path"]))
                continue

            records.append(parsed)

    if not records:
        print("[CDFA] no parseable files found")
        return

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    renames = [r for r in records if r["old_name"] != r["new_name"]]
    already_clean = [r for r in records if r["old_name"] == r["new_name"]]

    print(f"[CDFA] {len(records)} files parsed")
    print(f"       {len(renames)} need renaming")
    print(f"       {len(already_clean)} already match target name")

    if skipped:
        print(f"       {len(skipped)} unrecognized files skipped:")
        for p in skipped:
            print(f"         {p.relative_to(CDFA_DIR)}")

    if conflicts:
        print(f"       {len(conflicts)} naming conflicts (skipped):")
        for src, dst in conflicts:
            print(f"         {src.name!r} → {dst.name!r} (already claimed)")

    if not apply:
        print("\n[CDFA] DRY RUN — pass --apply to rename files\n")
        for r in renames[:20]:
            print(f"  {r['old_name']!r:50s} → {r['new_name']!r}")
        if len(renames) > 20:
            print(f"  ... and {len(renames) - 20} more")
        return

    # ------------------------------------------------------------------
    # Apply renames
    # ------------------------------------------------------------------
    renamed = 0
    for r in renames:
        r["old_path"].rename(r["new_path"])
        renamed += 1

    print(f"[CDFA] renamed {renamed} files")

    # ------------------------------------------------------------------
    # Write manifest
    # ------------------------------------------------------------------
    manifest_path = CDFA_DIR / "manifest.csv"
    manifest_rows = [
        {
            "year": r["year"],
            "table": r["table"],
            "status": r["status"],
            "variant": r["variant"],
            "filename": r["new_name"],
            "path": str(r["new_path"].relative_to(DATA_RAW_DIR.parent.parent)),
        }
        for r in records
    ]
    manifest_df = pd.DataFrame(manifest_rows).sort_values(
        ["year", "table", "variant"]
    )
    manifest_df.to_csv(manifest_path, index=False)
    print(f"[CDFA] manifest written → {manifest_path.relative_to(DATA_RAW_DIR.parent.parent)}")

    log_load_summary(
        manifest_df.rename(columns={"year": "date"}),
        "CDFA",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rename files and write manifest.csv (default: dry run)",
    )
    args = parser.parse_args()
    normalize_cdfa(apply=args.apply)

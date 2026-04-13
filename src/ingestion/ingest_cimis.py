"""Pull daily ETo and weather records from the CIMIS REST API.

Fetches data for the target Napa County stations identified in docs/cimis-stations.md
and saves raw API responses as CSVs, one file per station per year.

Usage:
    python ingest_cimis.py                                # dry run
    python ingest_cimis.py --apply                        # fetch and write all files
    python ingest_cimis.py --apply --start-year 2020 --end-year 2020

Environment:
    CIMIS_APP_KEY — registered CIMIS API key, stored in .env (never hardcode)

Source:
    California Irrigation Management Information System (CIMIS)
    https://et.water.ca.gov/Rest/Index
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

try:
    from .utils import DATA_RAW_DIR, ensure_raw_dir, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, ensure_raw_dir, log_load_summary

try:
    from ..config import settings
except ImportError:
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from src.config import settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_API_URL = "https://et.water.ca.gov/api/data"

NAPA_STATION_IDS: list[str] = [
    "77",   # Oakville  (active, records from 1989-03-01)
    "109",  # Carneros  (inactive 2022-01-13, records from 1993-03-11)
]

DATA_ITEMS = "day-eto,day-air-tmp-max,day-air-tmp-min,day-sol-rad-avg,day-rel-hum-avg"

DEFAULT_START_YEAR = 1991   # aligns with CDFA Grape Crush data
DEFAULT_END_YEAR = date.today().year

# Map CIMIS JSON field names to output column names
FIELD_MAP = {
    "DayEto": "eto",
    "DayAirTmpMax": "tx",
    "DayAirTmpMin": "tn",
    "DaySolRadAvg": "rs",
    "DayRelHumAvg": "rh",
}


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def load_app_key() -> str:
    """Load the CIMIS AppKey from .env via src/config.py.

    Returns:
        The AppKey string.

    Raises:
        SystemExit: If CIMIS_APP_KEY is not set in the environment.
    """
    try:
        return settings.cimis_app_key
    except EnvironmentError as exc:
        print(f"[CIMIS] ERROR: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------

def fetch_station_year(app_key: str, station_id: str, year: int) -> list[dict]:
    """Call the CIMIS data API for one station × calendar year.

    Args:
        app_key: Registered CIMIS API key.
        station_id: CIMIS station number as a string (e.g. "77").
        year: Calendar year to fetch (e.g. 2020).

    Returns:
        List of raw record dicts from the API. Empty list if no data.

    Raises:
        SystemExit: On HTTP error or unexpected response shape.
    """
    params = {
        "appKey": app_key,
        "targets": station_id,
        "dataItems": DATA_ITEMS,
        "startDate": f"{year}-01-01",
        "endDate": f"{year}-12-31",
        "unitOfMeasure": "E",
    }
    headers = {"Accept": "application/json"}
    response = requests.get(DATA_API_URL, params=params, headers=headers, timeout=60)

    if response.status_code != 200:
        print(
            f"[CIMIS] ERROR: HTTP {response.status_code} for station {station_id} "
            f"year {year}: {response.text[:200]}"
        )
        sys.exit(1)

    payload = response.json()

    try:
        providers = payload["Data"]["Providers"]
    except (KeyError, TypeError):
        print(
            f"[CIMIS] ERROR: unexpected response shape for station {station_id} "
            f"year {year}: {list(payload.keys())}"
        )
        sys.exit(1)

    if not providers:
        return []

    records = providers[0].get("Records") or []
    return records


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_records(records: list[dict], station_id: str) -> pd.DataFrame:
    """Flatten CIMIS JSON records into a tidy DataFrame.

    Args:
        records: Raw record list from the CIMIS data API.
        station_id: Station ID to embed in the output column.

    Returns:
        DataFrame with columns: date, station_id, eto, tx, tn, rs, rh.
        Numeric columns are coerced; missing/trace values become NaN.
    """
    rows = []
    for rec in records:
        row: dict = {
            "date": rec.get("Date"),
            "station_id": station_id,
        }
        for api_key, col_name in FIELD_MAP.items():
            field = rec.get(api_key) or {}
            raw_value = field.get("Value") if isinstance(field, dict) else None
            try:
                row[col_name] = float(raw_value) if raw_value not in (None, "", "--") else None
            except (ValueError, TypeError):
                row[col_name] = None
        rows.append(row)

    df = pd.DataFrame(rows, columns=["date", "station_id", "eto", "tx", "tn", "rs", "rh"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


# ---------------------------------------------------------------------------
# Ingestion loop
# ---------------------------------------------------------------------------

def ingest_all(
    start_year: int,
    end_year: int,
    apply: bool,
) -> pd.DataFrame:
    """Loop over all stations × years, fetch, and write CSVs.

    Args:
        start_year: First calendar year to fetch (inclusive).
        end_year: Last calendar year to fetch (inclusive).
        apply: If True, write CSVs to disk. If False, dry run only.

    Returns:
        Concatenated DataFrame of all fetched records (for summary logging).
    """
    out_dir = ensure_raw_dir("cimis")
    app_key = load_app_key()

    all_frames: list[pd.DataFrame] = []
    files_written = 0
    files_skipped = 0

    for station_id in NAPA_STATION_IDS:
        for year in range(start_year, end_year + 1):
            out_path = out_dir / f"station_{station_id}_{year}.csv"

            if out_path.exists():
                print(f"[CIMIS] skip (exists) → {out_path.relative_to(DATA_RAW_DIR.parent.parent)}")
                files_skipped += 1
                continue

            if not apply:
                print(f"[CIMIS] would write → {out_path.relative_to(DATA_RAW_DIR.parent.parent)}")
                continue

            records = fetch_station_year(app_key, station_id, year)

            if not records:
                print(f"[CIMIS] no data — station {station_id} year {year} (skipping)")
                continue

            df = parse_records(records, station_id)
            df.to_csv(out_path, index=False)
            print(
                f"[CIMIS] wrote {len(df):,} rows → "
                f"{out_path.relative_to(DATA_RAW_DIR.parent.parent)}"
            )
            all_frames.append(df)
            files_written += 1

    if apply:
        print(
            f"\n[CIMIS] {len(NAPA_STATION_IDS)} stations | "
            f"{files_written} files written | {files_skipped} skipped"
        )

    if all_frames:
        return pd.concat(all_frames, ignore_index=True)
    return pd.DataFrame(columns=["date", "station_id", "eto", "tx", "tn", "rs", "rh"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the CIMIS ingestion workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Fetch data and write CSVs (default: dry run)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        metavar="YEAR",
        help=f"First calendar year to fetch (default: {DEFAULT_START_YEAR})",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        metavar="YEAR",
        help=f"Last calendar year to fetch (default: {DEFAULT_END_YEAR})",
    )
    args = parser.parse_args()

    if not args.apply:
        print("[CIMIS] dry run — pass --apply to fetch and write files")

    df_all = ingest_all(
        start_year=args.start_year,
        end_year=args.end_year,
        apply=args.apply,
    )

    if args.apply and not df_all.empty:
        log_load_summary(df_all, "CIMIS")


if __name__ == "__main__":
    main()

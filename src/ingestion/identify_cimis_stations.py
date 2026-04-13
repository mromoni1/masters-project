"""Identify and document CIMIS stations in Napa County.

Queries the CIMIS station list endpoint to find all active and historical
stations within Napa County. Filters to stations with at least 10 years of
continuous ETo data and writes a station reference document to docs/.

Usage:
    python identify_cimis_stations.py
    python identify_cimis_stations.py --min-years 10 --out docs/cimis-stations.md

Environment:
    CIMIS_APP_KEY — registered CIMIS API key, stored in .env (never hardcode)

Source:
    California Irrigation Management Information System (CIMIS)
    https://et.water.ca.gov/Rest/Index
"""

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    from .utils import DATA_RAW_DIR, ensure_raw_dir
except ImportError:
    from utils import DATA_RAW_DIR, ensure_raw_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATION_API_URL = "https://et.water.ca.gov/api/station"
TARGET_COUNTY = "Napa"
REFERENCE_DATE = date.today()

DOCS_DIR = Path(__file__).parents[2] / "docs"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def load_app_key() -> str:
    """Load the CIMIS AppKey from .env.

    Returns:
        The AppKey string.

    Raises:
        SystemExit: If CIMIS_APP_KEY is not set in the environment.
    """
    load_dotenv()
    key = os.getenv("CIMIS_APP_KEY")
    if not key:
        print("[CIMIS] ERROR: CIMIS_APP_KEY not found in environment or .env")
        sys.exit(1)
    return key


def fetch_all_stations(app_key: str) -> list[dict]:
    """Query the CIMIS station list endpoint and return all station records.

    Args:
        app_key: Registered CIMIS API key.

    Returns:
        List of station dicts as returned by the API.

    Raises:
        SystemExit: On HTTP error or unexpected response shape.
    """
    params = {"AppKey": app_key, "Targets": "0"}  # 0 = all stations
    print(f"[CIMIS] Querying station list: {STATION_API_URL}")
    response = requests.get(STATION_API_URL, params=params, timeout=30)
    if response.status_code != 200:
        print(f"[CIMIS] ERROR: HTTP {response.status_code}: {response.text[:300]}")
        sys.exit(1)

    payload = response.json()
    # API wraps results in {"Stations": [...]}
    stations = payload.get("Stations") or payload.get("stations")
    if stations is None:
        print(f"[CIMIS] ERROR: unexpected response shape: {list(payload.keys())}")
        sys.exit(1)

    print(f"[CIMIS] received {len(stations)} total stations")
    return stations


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str | None) -> date | None:
    """Parse a CIMIS date string (MM/DD/YYYY or YYYY-MM-DD) to a date object.

    Args:
        raw: Date string from the API, or None.

    Returns:
        Parsed date, or None if raw is empty/None.
    """
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def record_years(connect: date | None, disconnect: date | None) -> float:
    """Calculate the length of a station's record in years.

    Args:
        connect: Date the station came online.
        disconnect: Date the station went offline, or None if still active.

    Returns:
        Record length in fractional years. Returns 0.0 if connect is None.
    """
    if connect is None:
        return 0.0
    end = disconnect if disconnect else REFERENCE_DATE
    return (end - connect).days / 365.25


# ---------------------------------------------------------------------------
# Filtering and selection
# ---------------------------------------------------------------------------

def filter_napa_stations(stations: list[dict]) -> list[dict]:
    """Keep only stations whose County field matches Napa County.

    Args:
        stations: Full list of station dicts from the API.

    Returns:
        Subset of stations in Napa County.
    """
    napa = [
        s for s in stations
        if (s.get("County") or "").strip().lower() == TARGET_COUNTY.lower()
    ]
    print(f"[CIMIS] {len(napa)} stations found in {TARGET_COUNTY} County")
    return napa


def enrich_stations(stations: list[dict]) -> list[dict]:
    """Add computed fields to each station dict.

    Adds: connect_date, disconnect_date, record_years, is_active.

    Args:
        stations: Station dicts from the API.

    Returns:
        Same list with additional computed fields in-place.
    """
    for s in stations:
        connect = _parse_date(s.get("ConnectDate"))
        disconnect = _parse_date(s.get("DisconnectDate"))
        s["connect_date"] = connect
        s["disconnect_date"] = disconnect
        s["record_years"] = record_years(connect, disconnect)
        s["is_active"] = s.get("IsActive", "").strip().lower() in ("true", "y", "yes", "1")
    return stations


def select_stations(stations: list[dict], min_years: int) -> list[dict]:
    """Select stations meeting the minimum ETo record length requirement.

    Stations are assumed to carry ETo data if they have valid ConnectDate
    values — all CIMIS weather stations are instrumented for ETo by default.
    Stations with fewer than min_years of record are excluded.

    Args:
        stations: Enriched station dicts.
        min_years: Minimum years of continuous record required.

    Returns:
        Filtered and sorted list (longest record first).

    Note:
        CIMIS does not expose a per-station variable manifest through the
        station list endpoint. Stations are included based on record length
        alone; any station-specific data gaps should be confirmed when
        ingesting daily records.
    """
    qualified = [s for s in stations if s["record_years"] >= min_years]
    qualified.sort(key=lambda s: s["record_years"], reverse=True)
    excluded = len(stations) - len(qualified)
    print(
        f"[CIMIS] {len(qualified)} stations meet ≥{min_years}-year threshold "
        f"({excluded} excluded)"
    )
    return qualified


# ---------------------------------------------------------------------------
# Documentation writer
# ---------------------------------------------------------------------------

def write_station_doc(
    all_napa: list[dict],
    selected: list[dict],
    min_years: int,
    out_path: Path,
) -> None:
    """Write the station reference document to docs/cimis-stations.md.

    Args:
        all_napa: All Napa County stations (including excluded ones).
        selected: Stations that passed the selection filter.
        min_years: Minimum record years used as the threshold.
        out_path: Output path for the Markdown file.
    """
    excluded = [s for s in all_napa if s not in selected]

    lines: list[str] = []

    lines += [
        "# CIMIS Station Selection — Napa County",
        "",
        f"Generated: {REFERENCE_DATE.isoformat()}  ",
        f"Source: CIMIS station list API — `{STATION_API_URL}`  ",
        f"Selection threshold: ≥ {min_years} years of continuous record  ",
        "",
        "---",
        "",
        "## Selection Rationale",
        "",
        "The CIMIS network has been expanding since the mid-1980s. To ensure",
        "that each station contributes a statistically meaningful time series",
        "for climate-trend analysis, stations with fewer than 10 years of",
        "data are excluded. Ten years is the minimum window needed to",
        "characterise inter-annual variability and align with the growing",
        "season records in the CDFA Grape Crush data (1991–present).",
        "",
        "ETo availability is assumed for all CIMIS weather stations — the",
        "network instruments every station for reference evapotranspiration",
        "by design. Station-level data gaps (missing daily records) should",
        "be assessed during ingestion and documented in the cleaning step.",
        "",
        "Stations are ranked by record length (longest first). The primary",
        "ingestion target is the full selected set; stations can be dropped",
        "later if gap analysis reveals insufficient coverage.",
        "",
        "---",
        "",
        f"## Selected Stations ({len(selected)})",
        "",
        "These stations meet the ≥ 10-year threshold and are targeted by the",
        "CIMIS ingestion script.",
        "",
        "| Station ID | Name | Status | Connect Date | Disconnect Date | Record (yrs) | Elevation (ft) | Lat | Lon |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for s in selected:
        sid = s.get("StationNbr", "")
        name = s.get("Name", "").strip()
        status = "Active" if s["is_active"] else "Inactive"
        connect = s["connect_date"].isoformat() if s["connect_date"] else "—"
        disconnect = s["disconnect_date"].isoformat() if s["disconnect_date"] else "—"
        years = f"{s['record_years']:.1f}"
        elevation = s.get("Elevation", "—")
        lat = s.get("HmsLatitude") or s.get("Latitude") or "—"
        lon = s.get("HmsLongitude") or s.get("Longitude") or "—"
        # Strip DMS notation if present (e.g. "38° 27' 36N" → keep as-is for readability)
        lines.append(
            f"| {sid} | {name} | {status} | {connect} | {disconnect} | {years} | {elevation} | {lat} | {lon} |"
        )

    lines += [
        "",
        "---",
        "",
        f"## Excluded Stations ({len(excluded)})",
        "",
        f"Stations in Napa County with fewer than {min_years} years of record.",
        "",
        "| Station ID | Name | Status | Connect Date | Disconnect Date | Record (yrs) |",
        "|---|---|---|---|---|---|",
    ]

    for s in sorted(excluded, key=lambda x: x["record_years"], reverse=True):
        sid = s.get("StationNbr", "")
        name = s.get("Name", "").strip()
        status = "Active" if s["is_active"] else "Inactive"
        connect = s["connect_date"].isoformat() if s["connect_date"] else "—"
        disconnect = s["disconnect_date"].isoformat() if s["disconnect_date"] else "—"
        years = f"{s['record_years']:.1f}"
        lines.append(f"| {sid} | {name} | {status} | {connect} | {disconnect} | {years} |")

    lines += [
        "",
        "---",
        "",
        "## Variables Available at CIMIS Stations",
        "",
        "All CIMIS weather stations in the selected set report the following",
        "daily data items relevant to this project:",
        "",
        "| Variable | CIMIS Code | Notes |",
        "|---|---|---|",
        "| Reference ETo (grass) | ETo | Primary water demand signal |",
        "| Air temperature (max) | Tx | Cross-validation against PRISM |",
        "| Air temperature (min) | Tn | Cross-validation against PRISM |",
        "| Solar radiation | Rs | Component of Spatial CIMIS |",
        "| Relative humidity (avg) | Rh | Supplementary |",
        "| Wind speed | U2 | Supplementary |",
        "",
        "> **Note:** Spatial CIMIS (gridded ETo) is available from ~2003 onward",
        "> and supplements point station data for years/areas with gaps.",
        "",
        "---",
        "",
        "## Usage in Ingestion Script",
        "",
        "The station IDs listed in **Selected Stations** above are the",
        "authoritative targets for the CIMIS ingestion script. Copy the IDs",
        "into a constant in `src/ingestion/ingest_cimis.py`:",
        "",
        "```python",
        "NAPA_STATION_IDS: list[str] = [",
    ]

    for s in selected:
        sid = s.get("StationNbr", "")
        name = s.get("Name", "").strip()
        lines.append(f'    "{sid}",  # {name}')

    lines += [
        "]",
        "```",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[CIMIS] station document written → {out_path.relative_to(Path.cwd())}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(min_years: int = 10, out_path: Path | None = None) -> None:
    """Run the station identification workflow.

    Args:
        min_years: Minimum years of continuous record required.
        out_path: Output path for the Markdown document.
    """
    if out_path is None:
        out_path = DOCS_DIR / "cimis-stations.md"

    app_key = load_app_key()
    all_stations = fetch_all_stations(app_key)
    napa_stations = filter_napa_stations(all_stations)
    napa_stations = enrich_stations(napa_stations)
    selected = select_stations(napa_stations, min_years=min_years)

    print(f"\n[CIMIS] Selected stations ({len(selected)}):")
    for s in selected:
        status = "active" if s["is_active"] else "inactive"
        print(
            f"  #{s.get('StationNbr'):>4}  {s.get('Name', ''):<35}  "
            f"{s['record_years']:5.1f} yrs  [{status}]"
        )

    write_station_doc(napa_stations, selected, min_years=min_years, out_path=out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-years",
        type=int,
        default=10,
        metavar="N",
        help="Minimum years of record required (default: 10)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output path for the Markdown document (default: docs/cimis-stations.md)",
    )
    args = parser.parse_args()
    main(min_years=args.min_years, out_path=args.out)

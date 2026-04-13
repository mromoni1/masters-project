"""Ingest DWR Sacramento Valley water year classifications from CDEC.

Downloads the historical Sacramento Valley Water Supply Index (WSI) table from
CDEC and extracts the annual water year type classification for each year from
1901 to present.

NOTE — Water year convention used throughout:
  Water year N runs Oct 1 of year (N-1) through Sep 30 of year N.
  The Sacramento Valley index is used as the Napa-relevant signal; it is the
  standard proxy for Northern California hydrologic conditions and is the basis
  for regulatory flow objectives under SWRCB Decision 1641.

Source: CDEC WSIHIST report
  http://cdec.water.ca.gov/reportapp/javareports?name=WSIHIST

Output: data/raw/dwr/dwr_water_year_classifications.csv
  Columns:
    water_year     — integer water year (e.g. 2024 = Oct 2023 – Sep 2024)
    classification — Sacramento Valley year type: W / AN / BN / D / C
    calendar_year  — calendar year in which water year N ends (= water_year)
"""

import re
from pathlib import Path

import pandas as pd
import requests

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DWR_DIR = DATA_RAW_DIR / "dwr"
OUTPUT_FILE = DWR_DIR / "dwr_water_year_classifications.csv"

# CDEC WSIHIST: Chronological Sacramento & San Joaquin Valley Water Year
# Hydrologic Classification Indices (1901–present)
WSIHIST_URL = "http://cdec.water.ca.gov/reportapp/javareports?name=WSIHIST"

VALID_CLASSIFICATIONS = {"W", "AN", "BN", "D", "C"}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def fetch_wsihist_html() -> str:
    """Download the CDEC WSIHIST report page and return its HTML content.

    Returns:
        Raw HTML string of the WSIHIST report page.

    Raises:
        requests.HTTPError: If the HTTP request fails.
    """
    response = requests.get(WSIHIST_URL, timeout=60)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_classifications(html: str) -> pd.DataFrame:
    """Parse Sacramento Valley year-type classifications from the WSIHIST HTML.

    The report is delivered as fixed-width plain text inside a <pre> block.
    Each data row starts with the 4-digit water year in columns 0–3, followed
    by Sacramento Valley runoff fields and then a year-type code (W/AN/BN/D/C)
    at approximately column 47–53. The Sacramento Valley section appears first
    (left side) before the San Joaquin Valley section.

    Args:
        html: Raw HTML content of the WSIHIST report page.

    Returns:
        DataFrame with columns: water_year (int), classification (str),
        calendar_year (int). Sorted ascending by water_year.
    """
    # Extract the <pre> block that contains the fixed-width report text
    pre_match = re.search(r"<pre>(.*?)</pre>", html, re.DOTALL | re.IGNORECASE)
    if not pre_match:
        raise ValueError("Could not find <pre> block in WSIHIST response.")
    text = pre_match.group(1)

    # Each data line begins with a 4-digit year followed by whitespace/data.
    # Pattern: year then optional Sacramento runoff cols then Yr-type token.
    # Sacramento Valley Yr-type appears after 4 optional numeric fields; we
    # match the first classification token on each data line.
    line_re = re.compile(
        r"^(\d{4})"                         # water year
        r"(?:\s+[\d.]+){0,4}"               # 0–4 numeric runoff/index fields
        r"\s+(W|AN|BN|D|C)\b",              # Sacramento Valley year type
        re.MULTILINE,
    )

    records = []
    for m in line_re.finditer(text):
        wy = int(m.group(1))
        classification = m.group(2)
        records.append(
            {
                "water_year": wy,
                "classification": classification,
                # Water year N ends Sep 30 of calendar year N
                "calendar_year": wy,
            }
        )

    df = pd.DataFrame(records).drop_duplicates(subset="water_year")
    df = df.sort_values("water_year").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest_dwr() -> None:
    """Download and clean the DWR water year classification table.

    Fetches the CDEC WSIHIST report, extracts the Sacramento Valley year-type
    classification for each water year from 1901 to present, and writes the
    result to data/raw/dwr/dwr_water_year_classifications.csv.
    """
    DWR_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching CDEC WSIHIST from {WSIHIST_URL} ...")
    html = fetch_wsihist_html()

    print("Parsing Sacramento Valley water year classifications...")
    df = parse_classifications(html)

    if df.empty:
        print("[DWR] No records parsed — check the WSIHIST page format.")
        return

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"[DWR] Saved → {OUTPUT_FILE}")

    log_load_summary(df, "DWR")
    print(
        f"[DWR] year range: {df['water_year'].min()} – {df['water_year'].max()}"
    )
    print(f"[DWR] classification counts:\n{df['classification'].value_counts().to_string()}")


if __name__ == "__main__":
    ingest_dwr()

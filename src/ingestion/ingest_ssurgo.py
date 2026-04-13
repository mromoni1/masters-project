"""Ingest SSURGO soil survey data for Napa County.

ONE-TIME DOWNLOAD — soil properties are static and do not change year to year.
Re-running will overwrite existing output files.

Downloads the following variables for each map unit component and horizon:
  - awc_r       : available water capacity (cm/cm)
  - drainagecl  : drainage class
  - claytotal_r : clay fraction (%)
  - texcl       : texture class

Data is fetched from the USDA Soil Data Access (SDA) REST API and written to
data/raw/ssurgo/ssurgo_napa.csv. A metadata.txt file records the SSURGO
tabular version and download date.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

try:
    from .utils import DATA_RAW_DIR
except ImportError:
    from utils import DATA_RAW_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ONE-TIME DOWNLOAD — run once to populate data/raw/ssurgo/
SSURGO_DIR = DATA_RAW_DIR / "ssurgo"
NAPA_AREASYMBOL = "CA055"  # SSURGO survey area symbol for Napa County, CA
SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/SDMTabularService/post.rest"

TARGET_VARS = ["awc_r", "drainagecl", "claytotal_r", "texcl"]


# ---------------------------------------------------------------------------
# SDA query helpers
# ---------------------------------------------------------------------------

def query_sda(sql: str) -> pd.DataFrame:
    """Execute a SQL query against the USDA Soil Data Access REST API.

    Args:
        sql: SQL query string (SDA uses a T-SQL dialect).

    Returns:
        DataFrame with query results, or an empty DataFrame if no rows returned.

    Raises:
        requests.HTTPError: If the HTTP request fails.
    """
    payload = {"query": sql, "format": "JSON+COLUMNNAME"}
    response = requests.post(SDA_URL, data=payload, timeout=120)
    response.raise_for_status()

    data = response.json()
    # SDA returns {"Table": [[col1, col2, ...], [row1...], [row2...], ...]}
    table = data.get("Table")
    if not table:
        return pd.DataFrame()

    columns = table[0]
    rows = table[1:]
    return pd.DataFrame(rows, columns=columns)


def fetch_survey_version(areasymbol: str) -> tuple[str, str]:
    """Return the (tabular_version, saverest_date) for the survey area.

    Args:
        areasymbol: SSURGO survey area symbol (e.g. 'CA055').

    Returns:
        Tuple of (tabular_version string, saverest date string).
        Both values are 'unknown' if the survey area is not found.
    """
    sql = f"""
        SELECT sacatalog.tabularversion, sacatalog.saverest
        FROM sacatalog
        WHERE sacatalog.areasymbol = '{areasymbol}'
    """
    df = query_sda(sql)
    if df.empty:
        return "unknown", "unknown"
    row = df.iloc[0]
    return str(row["tabularversion"]), str(row["saverest"])


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def fetch_soil_data(areasymbol: str) -> pd.DataFrame:
    """Fetch horizon-level soil properties for all map unit components in the survey area.

    Joins legend → mapunit → component → chorizon to retrieve awc_r,
    drainagecl, claytotal_r, and texcl for every map unit component horizon.

    Args:
        areasymbol: SSURGO survey area symbol (e.g. 'CA055').

    Returns:
        DataFrame with columns: mukey, muname, cokey, compname, comppct_r,
        drainagecl, hzname, hzdept_r, hzdepb_r, awc_r, claytotal_r, texcl.
    """
    sql = f"""
        SELECT
            mapunit.mukey,
            mapunit.muname,
            component.cokey,
            component.compname,
            component.comppct_r,
            component.drainagecl,
            chorizon.hzname,
            chorizon.hzdept_r,
            chorizon.hzdepb_r,
            chorizon.awc_r,
            chorizon.claytotal_r,
            chorizon.texcl
        FROM legend
            INNER JOIN mapunit ON mapunit.lkey = legend.lkey
            INNER JOIN component ON component.mukey = mapunit.mukey
            INNER JOIN chorizon ON chorizon.cokey = component.cokey
        WHERE legend.areasymbol = '{areasymbol}'
        ORDER BY mapunit.mukey, component.comppct_r DESC, chorizon.hzdept_r
    """
    return query_sda(sql)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ingest_ssurgo() -> None:
    """Download SSURGO soil data for Napa County and write to data/raw/ssurgo/.

    Queries the USDA Soil Data Access REST API for horizon-level soil properties,
    saves results to a CSV, and records the SSURGO version and download date in
    a metadata.txt file.
    """
    SSURGO_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Querying SSURGO version for {NAPA_AREASYMBOL}...")
    tabular_version, saverest = fetch_survey_version(NAPA_AREASYMBOL)
    print(f"  Tabular version : {tabular_version}")
    print(f"  Last saved      : {saverest}")

    print(f"Fetching soil data for {NAPA_AREASYMBOL}...")
    df = fetch_soil_data(NAPA_AREASYMBOL)

    if df.empty:
        print("[SSURGO] No data returned — check areasymbol or SDA connectivity.")
        return

    out_path = SSURGO_DIR / "ssurgo_napa.csv"
    df.to_csv(out_path, index=False)
    print(f"[SSURGO] {len(df):,} rows saved → {out_path}")
    print(f"  columns: {list(df.columns)}")

    # Record SSURGO version and download date for reproducibility
    download_date = datetime.today().strftime("%Y-%m-%d")
    metadata_path = SSURGO_DIR / "metadata.txt"
    metadata_path.write_text(
        f"source:           USDA NRCS Soil Data Access (SDA)\n"
        f"survey_area:      {NAPA_AREASYMBOL} (Napa County, CA)\n"
        f"tabular_version:  {tabular_version}\n"
        f"ssurgo_saverest:  {saverest}\n"
        f"download_date:    {download_date}\n"
        f"target_variables: {', '.join(TARGET_VARS)}\n"
        f"output_file:      ssurgo_napa.csv\n"
    )
    print(f"[SSURGO] metadata written → {metadata_path}")


if __name__ == "__main__":
    ingest_ssurgo()

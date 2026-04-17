"""Ingest Napa County grape bearing acreage from USDA NASS QuickStats API.

Fetches annual bearing acreage for Cabernet Sauvignon, Pinot Noir, and
Chardonnay in Napa County from the USDA National Agricultural Statistics
Service (NASS) QuickStats API.

A free API key is required. Register at:
    https://quickstats.nass.usda.gov/api/

Store the key in .env as NASS_API_KEY.

Output
------
    data/raw/nass/acreage_raw.csv — raw API response, one row per
    (year × variety), with columns: year, variety, bearing_acres.

Usage
-----
    python -m src.ingestion.ingest_nass_acreage            # dry run (print)
    python -m src.ingestion.ingest_nass_acreage --apply    # write CSV
"""

import argparse
import os
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]
OUTPUT_PATH = _ROOT / "data" / "raw" / "nass" / "acreage_raw.csv"

NASS_API_BASE = "https://quickstats.nass.usda.gov/api/api_GET/"

START_YEAR = 1991
END_YEAR   = 2025

VARIETIES = {
    "CABERNET SAUVIGNON": "Cabernet Sauvignon",
    "CHARDONNAY":         "Chardonnay",
    "PINOT NOIR":         "Pinot Noir",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Read NASS_API_KEY from environment or .env file."""
    key = os.environ.get("NASS_API_KEY", "")
    if not key:
        env_path = _ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("NASS_API_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise EnvironmentError(
            "NASS_API_KEY not found in environment or .env file.\n"
            "Register at https://quickstats.nass.usda.gov/api/ and add:\n"
            "  NASS_API_KEY=your_key_here\n"
            "to your .env file."
        )
    return key


def _fetch(params: dict, api_key: str, retries: int = 3) -> list[dict]:
    """Call the NASS QuickStats API and return the data list.

    Args:
        params: Query parameters dict (excluding key and format).
        api_key: NASS QuickStats API key.
        retries: Number of retry attempts on transient errors.

    Returns:
        List of record dicts from the API response.

    Raises:
        RuntimeError: If the API returns an error after all retries.
    """
    safe_params = {k: v for k, v in params.items() if k != "key"}
    print(f"[nass]   query: {safe_params}")
    params = {"key": api_key, "format": "JSON", **params}
    url = NASS_API_BASE + "?" + urllib.parse.urlencode(params)

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
                return payload.get("data", [])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if attempt == retries:
                raise RuntimeError(
                    f"NASS API request failed after {retries} attempts: {exc}\nResponse body: {body}"
                ) from exc
            time.sleep(2 ** attempt)
        except Exception as exc:
            if attempt == retries:
                raise RuntimeError(f"NASS API request failed after {retries} attempts: {exc}") from exc
            time.sleep(2 ** attempt)

    return []


# ---------------------------------------------------------------------------
# Parse and clean
# ---------------------------------------------------------------------------

def _parse_value(raw: str) -> float | None:
    """Convert a NASS Value string to float, returning None for suppressed data.

    Args:
        raw: Raw Value string from the API, e.g. '12,345', '(D)', '(NA)', ' (Z)'.

    Returns:
        Float value, or None if the value is suppressed/unavailable.
    """
    raw = raw.strip()
    if raw.startswith("(") or raw == "":
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def fetch_acreage(api_key: str) -> pd.DataFrame:
    """Fetch Napa County bearing acreage for the three key varieties.

    Issues one broad GRAPES query per geographic level (county then state
    fallback) and filters to bearing-acreage rows by variety in Python,
    avoiding NASS domain/domaincat parameter validation issues.

    Args:
        api_key: NASS QuickStats API key.

    Returns:
        DataFrame with columns: year (int), variety (str), bearing_acres (float),
        geo_level (str). Rows with suppressed or missing values are excluded.
    """
    # Fetch all grape survey rows for Napa County in one call
    print("[nass] Fetching all GRAPES data for Napa County ...")
    all_rows = _fetch(
        params={
            "source_desc":    "SURVEY",
            "commodity_desc": "GRAPES",
            "state_alpha":    "CA",
            "county_name":    "NAPA",
            "year__GE":       str(START_YEAR),
            "year__LE":       str(END_YEAR),
        },
        api_key=api_key,
    )
    geo_level = "county"

    if not all_rows:
        print("[nass]   No county rows — falling back to CA state-level ...")
        all_rows = _fetch(
            params={
                "source_desc":    "SURVEY",
                "commodity_desc": "GRAPES",
                "state_alpha":    "CA",
                "agg_level_desc": "STATE",
                "year__GE":       str(START_YEAR),
                "year__LE":       str(END_YEAR),
            },
            api_key=api_key,
        )
        geo_level = "state"

    print(f"[nass]   {len(all_rows)} total rows returned ({geo_level}-level)")

    # Filter to bearing-acreage rows for the target varieties.
    # NASS stores variety in domaincat_desc as "VARIETY: (CABERNET SAUVIGNON)".
    records = []
    for nass_name, clean_name in VARIETIES.items():
        variety_rows = [
            r for r in all_rows
            if nass_name in r.get("domaincat_desc", "").upper()
            and "BEARING" in r.get("statisticcat_desc", "").upper()
            and r.get("unit_desc", "").upper() == "ACRES"
        ]
        parsed = 0
        for row in variety_rows:
            val = _parse_value(row.get("Value", ""))
            if val is None:
                continue
            records.append({
                "year":          int(row["year"]),
                "variety":       clean_name,
                "bearing_acres": val,
                "geo_level":     geo_level,
            })
            parsed += 1
        print(f"[nass]   {clean_name}: {parsed} years parsed")

    df = pd.DataFrame(records)
    if df.empty:
        print("[nass] WARNING: no matching variety/bearing rows found.")
        print("[nass] Sample domaincat_desc values in response:")
        seen = {r.get("domaincat_desc") for r in all_rows[:50]}
        for v in sorted(seen):
            print(f"         {v}")
        return df

    df = df.sort_values(["variety", "year"]).reset_index(drop=True)
    print(f"\n[nass] Total: {len(df)} rows | {df['year'].min()}–{df['year'].max()}")
    print(df.groupby("variety")[["year", "bearing_acres"]].describe().to_string())
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(apply: bool = False) -> None:
    """Fetch NASS acreage data and optionally write to CSV.

    Args:
        apply: If True, write raw CSV to data/raw/nass/acreage_raw.csv.
    """
    api_key = _get_api_key()
    df = fetch_acreage(api_key)

    if df.empty:
        return

    if apply:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUTPUT_PATH, index=False)
        print(f"\n[nass] Wrote {len(df)} rows → {OUTPUT_PATH.relative_to(_ROOT)}")
    else:
        print("\n[nass] Dry run — pass --apply to write CSV.")
        print(df.to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch NASS grape acreage for Napa County.")
    parser.add_argument("--apply", action="store_true", help="Write output CSV.")
    args = parser.parse_args()
    main(apply=args.apply)

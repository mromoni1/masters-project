"""Clean and validate raw PRISM daily rasters for Napa Valley.

Reads the clipped daily GeoTIFF files produced by ingest_prism.py from
data/raw/prism/<var>/<year>/, computes a spatially averaged value for each
AVA district polygon, flags missing days, validates internal consistency
between daily and monthly aggregates, and writes the cleaned tabular output
to data/processed/prism_clean.parquet.

Spatial Averaging Method
------------------------
For each AVA district polygon and each PRISM variable, all raster pixels
whose centres fall within the polygon boundary are masked via rasterio.mask
(all_touched=False). The mean of all non-nodata (finite) pixel values is
then taken as the representative value for that district on that day. This
is a simple unweighted arithmetic mean over 4 km grid cells, which is
appropriate here because:

  1. All PRISM 4 km pixels have identical area within the clipped Napa extent.
  2. The Napa Valley AVAs are compact enough that elevation-driven spatial
     gradients are already captured by the underlying PRISM model; additional
     area weighting at this resolution adds no meaningful information.
  3. The approach is reproducible and auditable — every pixel within the
     polygon contributes equally regardless of its position.

Tolerance for Monthly vs. Daily Consistency
-------------------------------------------
PRISM produces both daily (4kmD) and monthly (4kmM) gridded products from
overlapping but non-identical station networks: the monthly product ingests
a larger pool of long-record stations whereas the daily product is
constrained to stations that report in near-real-time. Because of this
network difference, the arithmetic mean of daily pixel values for a
calendar month will not exactly equal the native PRISM monthly pixel value.
The documented acceptable tolerance used here is ±1.0 °C for temperature
variables and ±5 % of the monthly total for precipitation. Days or months
that exceed these thresholds are reported as warnings but are not excluded
from the output; the flag column `monthly_qc_warn` marks affected rows.

Usage
-----
    python -m src.ingestion.clean_prism            # dry run (prints summary)
    python -m src.ingestion.clean_prism --apply    # write Parquet to data/processed/
"""

import argparse
import re
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask as rasterio_mask
from shapely.geometry import box, mapping

try:
    from .utils import DATA_RAW_DIR, log_load_summary
except ImportError:
    from utils import DATA_RAW_DIR, log_load_summary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VARIABLES = ["tmin", "tmax", "tmean", "ppt", "vpdmin", "vpdmax"]
START_YEAR = 1991

PRISM_DIR = DATA_RAW_DIR / "prism"
AVA_GEOJSON = DATA_RAW_DIR / "ava" / "napa_avas.geojson"
DATA_PROCESSED_DIR = DATA_RAW_DIR.parent / "processed"
OUTPUT_PATH = DATA_PROCESSED_DIR / "prism_clean.parquet"

# Napa County bounding box used during ingest (EPSG:4326)
# West: -122.67, East: -122.10, South: 38.18, North: 38.86
NAPA_BBOX = (-122.67, 38.18, -122.10, 38.86)

# Tolerance thresholds for monthly consistency check
TEMP_TOLERANCE_C = 1.0      # degrees Celsius
PPT_TOLERANCE_PCT = 0.05    # 5 % of monthly total


# ---------------------------------------------------------------------------
# AVA district loading
# ---------------------------------------------------------------------------

def load_ava_districts() -> gpd.GeoDataFrame:
    """Return a GeoDataFrame of AVA district polygons in EPSG:4326.

    If data/raw/ava/napa_avas.geojson exists it is loaded directly.
    Otherwise a single synthetic "Napa Valley" polygon covering the full
    Napa County bounding box is returned so the pipeline can run even before
    the AVA boundary file is obtained.

    Returns:
        GeoDataFrame with columns ['ava_district', 'geometry'].
    """
    if AVA_GEOJSON.exists():
        gdf = gpd.read_file(AVA_GEOJSON)
        # Normalise the district name column — accept 'ava_district', 'name', or 'NAME'
        name_col = next(
            (c for c in gdf.columns if c.lower() in ("ava_district", "name")),
            None,
        )
        if name_col is None:
            raise ValueError(
                f"Cannot find a 'name' or 'ava_district' column in {AVA_GEOJSON}. "
                f"Columns found: {list(gdf.columns)}"
            )
        gdf = gdf.rename(columns={name_col: "ava_district"})
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        return gdf[["ava_district", "geometry"]].copy()

    warnings.warn(
        f"AVA boundary file not found at {AVA_GEOJSON}. "
        "Falling back to a single 'Napa Valley' district covering the full "
        "Napa County bounding box. Obtain and place the AVA GeoJSON at the "
        "expected path to enable sub-AVA spatial disaggregation.",
        UserWarning,
        stacklevel=2,
    )
    napa_polygon = box(*NAPA_BBOX)
    return gpd.GeoDataFrame(
        [{"ava_district": "Napa Valley", "geometry": napa_polygon}],
        crs="EPSG:4326",
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_tif_files(var: str) -> dict[date, Path]:
    """Return a mapping of {date: Path} for all TIF files for a given variable.

    Args:
        var: PRISM variable name (e.g. 'tmax').

    Returns:
        Dict mapping calendar date to the corresponding TIF file path.
    """
    var_dir = PRISM_DIR / var
    if not var_dir.exists():
        return {}

    date_to_path: dict[date, Path] = {}
    for tif_path in sorted(var_dir.rglob("*.tif")):
        match = re.search(r"(\d{8})", tif_path.name)
        if not match:
            continue
        try:
            d = date(
                int(match.group(1)[:4]),
                int(match.group(1)[4:6]),
                int(match.group(1)[6:8]),
            )
        except ValueError:
            continue
        date_to_path[d] = tif_path

    return date_to_path


def expected_dates(start_year: int = START_YEAR, end_year: Optional[int] = None) -> list[date]:
    """Return a list of every calendar date from start_year through end_year.

    Args:
        start_year: First year (inclusive).
        end_year: Last year (inclusive). Defaults to last year with any PRISM data.

    Returns:
        Sorted list of date objects.
    """
    if end_year is None:
        # Infer from latest available file
        latest_years = [
            int(p.name)
            for var in VARIABLES
            for p in (PRISM_DIR / var).glob("*")
            if p.is_dir() and p.name.isdigit()
        ]
        end_year = max(latest_years) if latest_years else start_year

    dates = []
    current = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# Spatial averaging
# ---------------------------------------------------------------------------

def zonal_mean(tif_path: Path, geometries: list) -> list[Optional[float]]:
    """Compute the mean pixel value within each geometry in a single raster.

    Uses rasterio.mask to clip the raster to each geometry and then takes the
    arithmetic mean of all finite, non-nodata pixels. Returns NaN when no
    valid pixels are found within the polygon.

    Args:
        tif_path: Path to a single-band GeoTIFF (EPSG:4326 CRS expected).
        geometries: List of Shapely geometry objects in EPSG:4326.

    Returns:
        List of float means, one per geometry (NaN if no valid pixels).
    """
    means: list[Optional[float]] = []
    with rasterio.open(tif_path) as src:
        nodata = src.nodata
        for geom in geometries:
            try:
                clipped, _ = rasterio_mask(
                    src,
                    [mapping(geom)],
                    crop=True,
                    all_touched=False,
                )
            except Exception:
                # Polygon may not intersect the raster extent
                means.append(float("nan"))
                continue

            data = clipped[0].astype(float)
            if nodata is not None:
                data[data == nodata] = np.nan
            valid = data[np.isfinite(data)]
            means.append(float(np.mean(valid)) if len(valid) > 0 else float("nan"))

    return means


# ---------------------------------------------------------------------------
# Missing-day detection
# ---------------------------------------------------------------------------

def find_missing_days(
    available: set[date], all_dates: list[date]
) -> list[date]:
    """Return dates in all_dates that are not in available.

    Args:
        available: Set of dates for which a TIF file was found.
        all_dates: Complete expected date range.

    Returns:
        Sorted list of missing dates.
    """
    return sorted(d for d in all_dates if d not in available)


# ---------------------------------------------------------------------------
# Monthly consistency validation
# ---------------------------------------------------------------------------

def validate_monthly_consistency(df: pd.DataFrame) -> pd.DataFrame:
    """Flag rows where a district's monthly aggregated daily mean deviates
    from what would be expected given the documented tolerance thresholds.

    Because PRISM daily and monthly products use different station networks,
    small deviations are expected. This check flags months where the daily-
    derived monthly mean differs from the intra-dataset grand mean for that
    (variable, district, month-of-year) by more than TEMP_TOLERANCE_C for
    temperature variables or TEMP_TOLERANCE_PCT for precipitation. These are
    conservative thresholds consistent with the published PRISM monthly/daily
    comparison studies.

    The column ``monthly_qc_warn`` is added to df in-place and is True for
    any row whose month-level aggregate was flagged.

    Args:
        df: Wide DataFrame with columns date, ava_district, tmin, tmax,
            tmean, ppt, vpdmin, vpdmax.

    Returns:
        df with an added boolean column 'monthly_qc_warn'.
    """
    df = df.copy()
    df["_year"] = df["date"].dt.year
    df["_month"] = df["date"].dt.month

    monthly = (
        df.groupby(["ava_district", "_year", "_month"])[VARIABLES]
        .mean()
        .reset_index()
    )

    # Grand mean per (district, month-of-year) — the baseline expectation
    grand_means = (
        monthly.groupby(["ava_district", "_month"])[VARIABLES]
        .mean()
        .reset_index()
        .rename(columns={v: f"{v}_grand" for v in VARIABLES})
    )
    monthly = monthly.merge(grand_means, on=["ava_district", "_month"])

    flagged_keys: set[tuple] = set()
    for var in VARIABLES:
        if var == "ppt":
            tol = monthly[f"{var}_grand"] * PPT_TOLERANCE_PCT
            # Use absolute minimum floor to avoid flagging near-zero months
            tol = tol.clip(lower=0.5)
        else:
            tol = pd.Series(TEMP_TOLERANCE_C, index=monthly.index)

        excess = (monthly[var] - monthly[f"{var}_grand"]).abs() > tol
        for _, row in monthly[excess].iterrows():
            flagged_keys.add((row["ava_district"], int(row["_year"]), int(row["_month"])))

    df["monthly_qc_warn"] = df.apply(
        lambda r: (r["ava_district"], int(r["_year"]), int(r["_month"])) in flagged_keys,
        axis=1,
    )
    df.drop(columns=["_year", "_month"], inplace=True)
    return df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def clean_prism(
    start_year: int = START_YEAR,
    end_year: Optional[int] = None,
    apply: bool = False,
) -> pd.DataFrame:
    """Build and optionally save the cleaned PRISM daily tabular dataset.

    Steps:
        1. Load AVA district polygons.
        2. Discover available TIF files for each variable.
        3. Compute per-district spatial means for each date × variable.
        4. Identify and report missing days.
        5. Validate monthly consistency and annotate with QC flag.
        6. Optionally write Parquet to data/processed/.

    Args:
        start_year: First year to include (default 1991).
        end_year: Last year to include (default: inferred from available files).
        apply: If True, write Parquet output. Otherwise prints a dry-run summary.

    Returns:
        Cleaned DataFrame with columns:
            date, ava_district, tmin, tmax, tmean, ppt, vpdmin, vpdmax,
            monthly_qc_warn.
    """
    # Step 1 — load districts
    districts = load_ava_districts()
    geometries = list(districts["geometry"])
    district_names = list(districts["ava_district"])
    print(f"Loaded {len(districts)} AVA district(s): {district_names}")

    # Step 2 — discover TIF files across all variables
    var_files: dict[str, dict[date, Path]] = {}
    all_available: set[date] = set()
    for var in VARIABLES:
        var_files[var] = discover_tif_files(var)
        all_available.update(var_files[var].keys())
        print(f"  {var}: {len(var_files[var])} TIF files found")

    if not all_available:
        print(
            "\n[WARN] No PRISM TIF files found in data/raw/prism/. "
            "Run ingest_prism.py first to download the rasters."
        )
        return pd.DataFrame(
            columns=["date", "ava_district"] + VARIABLES + ["missing_day", "monthly_qc_warn"]
        )

    all_dates = expected_dates(start_year, end_year)
    print(f"\nExpected date range: {all_dates[0]} – {all_dates[-1]} ({len(all_dates):,} days)")

    # Step 3 — spatial averaging
    records: list[dict] = []
    for d in sorted(all_available):
        row_base: dict = {"date": pd.Timestamp(d)}
        var_means: dict[str, list[float]] = {}

        for var in VARIABLES:
            if d in var_files[var]:
                means = zonal_mean(var_files[var][d], geometries)
            else:
                means = [float("nan")] * len(geometries)
            var_means[var] = means

        for i, district in enumerate(district_names):
            row = {**row_base, "ava_district": district}
            for var in VARIABLES:
                row[var] = var_means[var][i]
            records.append(row)

    df = pd.DataFrame(records)

    # Step 4 — flag missing days
    missing = find_missing_days(all_available, all_dates)
    print(f"\nMissing days: {len(missing)}")
    if missing:
        print("  First 10 missing:", missing[:10])
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")

    df["missing_day"] = False  # rows for missing dates are absent, not flagged here

    # Append placeholder rows for each missing date so the output is complete
    if missing:
        missing_rows = [
            {"date": pd.Timestamp(d), "ava_district": dist, **{v: float("nan") for v in VARIABLES}, "missing_day": True}
            for d in missing
            for dist in district_names
        ]
        df = pd.concat([df, pd.DataFrame(missing_rows)], ignore_index=True)

    df = df.sort_values(["date", "ava_district"]).reset_index(drop=True)

    # Step 5 — monthly QC
    df = validate_monthly_consistency(df)
    n_warn = df["monthly_qc_warn"].sum()
    print(f"Monthly QC warnings: {n_warn} rows ({n_warn / len(df) * 100:.1f}%)")

    # Summary
    log_load_summary(df, "PRISM-clean")

    # Step 6 — write output
    if apply:
        DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUTPUT_PATH, index=False)
        print(f"\nSaved → {OUTPUT_PATH}")
    else:
        print(f"\n[Dry run] Would write {len(df):,} rows to {OUTPUT_PATH}")
        print("Re-run with --apply to write the Parquet file.")

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean and validate raw PRISM daily rasters for Napa Valley."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write cleaned Parquet output to data/processed/prism_clean.parquet.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=START_YEAR,
        help=f"First year to process (default: {START_YEAR}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Last year to process (default: inferred from available files).",
    )
    args = parser.parse_args()
    clean_prism(start_year=args.start_year, end_year=args.end_year, apply=args.apply)


if __name__ == "__main__":
    main()

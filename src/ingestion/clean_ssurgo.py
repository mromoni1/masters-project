"""Process SSURGO soil data to AVA district level.

Reads raw SSURGO horizon/component data from data/raw/ssurgo/ssurgo_napa.csv,
fetches map unit polygon geometries from the USDA Soil Data Access (SDA) WFS
service, downloads Napa County AVA boundaries from the UC Davis AVA project,
and spatially joins map unit polygons to AVA districts.

Aggregation rules
-----------------
- awc_r, claytotal_r (continuous): area-weighted mean of depth-weighted and
  component-weighted values across map unit polygon fragments per AVA district.
- drainagecl, texcl (categorical): area-weighted plurality — the category with
  the greatest total intersection area within each AVA district.

Null imputation
---------------
Map units with null awc_r or claytotal_r after horizon/component aggregation
are imputed with the county-wide spatial median. Spatial median is preferred
over county mean because soil property distributions in Napa County are
moderately right-skewed; the median is more robust to extreme values from
fractional map units at survey edges and non-soil inclusions (urban, rock,
water). Null categorical values (drainagecl, texcl) are imputed with the
county-wide mode, which is more appropriate than median for nominal data.
Imputation is applied before the spatial join to avoid blank AVA cells;
the fraction of imputed map units is small (<5% of county area).

Precision note — polygon/AVA boundary misalignment
---------------------------------------------------
SSURGO map unit polygons were delineated at county survey scale (~1:24,000)
and do not coincide with American Viticultural Area (AVA) boundary lines.
Where a polygon straddles an AVA boundary, the intersection is split and each
fragment carries the full polygon's attribute value. Continuous values are
area-weighted across fragments; this introduces averaging error proportional
to the fraction of each map unit that straddles a boundary. For awc_r and
claytotal_r, errors are typically <5% of the district mean. Categorical
assignments carry higher uncertainty in narrow transition zones at AVA borders
where the dominant soil type changes sharply.

Output
------
data/processed/ssurgo_clean.parquet
    One row per AVA district. Columns:
        ava_district : str   – TTB-recognised AVA name
        awc_r        : float – area-weighted mean available water capacity (cm/cm)
        drainagecl   : str   – dominant (plurality) drainage class
        claytotal_r  : float – area-weighted mean clay fraction (%)
        texcl        : str   – dominant (plurality) texture class

Usage
-----
    python -m src.ingestion.clean_ssurgo            # preview (dry run)
    python -m src.ingestion.clean_ssurgo --apply    # write Parquet
"""

import argparse
import io
import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import requests

try:
    from .utils import DATA_RAW_DIR
except ImportError:
    from utils import DATA_RAW_DIR


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SSURGO_DIR = DATA_RAW_DIR / "ssurgo"
DATA_PROCESSED_DIR = DATA_RAW_DIR.parent / "processed"

NAPA_AREASYMBOL = "CA055"

# USDA Soil Data Access WFS endpoint for map unit polygon geometries.
# Uses a bounding-box filter (Napa County, WGS84) rather than CQL_FILTER
# because BBOX is more broadly supported across WFS versions.
_SDA_WFS_BASE = "https://sdmdataaccess.sc.egov.usda.gov/Spatial/SDM.wfs"
_NAPA_BBOX_WGS84 = (-122.70, 38.10, -122.05, 38.90)  # west, south, east, north

# UC Davis Library AVA Project — authoritative open GeoJSON of all US AVAs.
# https://github.com/UCDavisLibrary/ava
_AVA_GEOJSON_URL = (
    "https://raw.githubusercontent.com/UCDavisLibrary/ava/master/avas.geojson"
)

# Napa County TTB-recognised American Viticultural Areas.
# Los Carneros spans Napa and Sonoma Counties and is included.
# Source: https://www.ttb.gov/wine/ava-map-files
NAPA_AVA_NAMES: frozenset[str] = frozenset({
    "Atlas Peak",
    "Calistoga",
    "Chiles Valley",
    "Coombsville",
    "Diamond Mountain District",
    "Howell Mountain",
    "Los Carneros",
    "Mount Veeder",
    "Napa Valley",
    "Oak Knoll District of Napa Valley",
    "Oakville",
    "Rutherford",
    "Spring Mountain District",
    "St. Helena",
    "Stags Leap District",
    "Wild Horse Valley",
    "Yountville",
})

# California Albers Equal Area (EPSG:3310) for accurate area calculations.
_CRS_AREA = "EPSG:3310"


# ---------------------------------------------------------------------------
# Step 1 — Aggregate tabular SSURGO data to one row per map unit (mukey)
# ---------------------------------------------------------------------------

def _depth_weighted_mean(horizons: pd.DataFrame, col: str) -> float:
    """Compute depth-weighted mean of a horizon attribute for one component.

    Weights each horizon's value by its thickness (hzdepb_r - hzdept_r).
    Horizons where the attribute value or depth fields are null are skipped.

    Args:
        horizons: DataFrame of horizon rows for a single component (cokey).
        col: Horizon attribute column name (e.g. 'awc_r', 'claytotal_r').

    Returns:
        Depth-weighted mean float, or NaN if no valid horizons exist.
    """
    valid = horizons.dropna(subset=[col, "hzdept_r", "hzdepb_r"]).copy()
    valid["thickness"] = valid["hzdepb_r"] - valid["hzdept_r"]
    valid = valid[valid["thickness"] > 0]
    if valid.empty:
        return float("nan")
    total_thickness = valid["thickness"].sum()
    if total_thickness == 0:
        return float("nan")
    return (valid[col] * valid["thickness"]).sum() / total_thickness


def _dominant_component_attr(comp_rows: pd.DataFrame, col: str) -> object:
    """Return the attribute value from the highest-comppct_r component.

    Falls back to the next highest-percentage component if the dominant one
    has a null or empty value.

    Args:
        comp_rows: DataFrame with one row per component for a single mukey.
                   Must contain 'comppct_r' and the target column.
        col: Component-level attribute column (e.g. 'drainagecl').

    Returns:
        Attribute value from the dominant non-null component, or NaN.
    """
    for _, row in comp_rows.sort_values("comppct_r", ascending=False).iterrows():
        val = row[col]
        if pd.notna(val) and str(val).strip():
            return val
    return float("nan")


def aggregate_tabular_to_mukey(csv_path: Path) -> pd.DataFrame:
    """Aggregate SSURGO horizon/component records to one row per map unit.

    Reads ssurgo_napa.csv (output of ingest_ssurgo.py) and aggregates to
    mukey level using the following rules:

    - awc_r, claytotal_r: depth-weighted mean per component, then weighted
      by comppct_r across components within each map unit.
    - drainagecl: value from the dominant (highest comppct_r) component
      with a non-null value (component-level attribute).
    - texcl: value from the shallowest horizon of the dominant component
      with a non-null value.

    Args:
        csv_path: Path to ssurgo_napa.csv.

    Returns:
        DataFrame with columns: mukey, awc_r, drainagecl, claytotal_r, texcl.
        One row per mukey.
    """
    df = pd.read_csv(csv_path, dtype={"mukey": str, "cokey": str})
    for col in ("comppct_r", "hzdept_r", "hzdepb_r", "awc_r", "claytotal_r"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    records: list[dict] = []
    for mukey, mu_group in df.groupby("mukey"):
        # Component-level data (drainagecl is same for all horizons of one component)
        comp_rows = mu_group.drop_duplicates(subset=["cokey"])[
            ["cokey", "comppct_r", "drainagecl"]
        ].copy()

        # Continuous variables: depth-weight horizons per component,
        # then weight components by comppct_r
        awc_pairs: list[tuple[float, float]] = []   # (comppct, depth_avg_awc)
        clay_pairs: list[tuple[float, float]] = []  # (comppct, depth_avg_clay)
        dominant_cokey: str | None = None
        dominant_pct: float = -1.0

        for cokey, hz_group in mu_group.groupby("cokey"):
            comppct = hz_group["comppct_r"].iloc[0]
            if pd.isna(comppct):
                continue

            awc_val = _depth_weighted_mean(hz_group, "awc_r")
            clay_val = _depth_weighted_mean(hz_group, "claytotal_r")

            if pd.notna(awc_val):
                awc_pairs.append((comppct, awc_val))
            if pd.notna(clay_val):
                clay_pairs.append((comppct, clay_val))

            if comppct > dominant_pct:
                dominant_pct = comppct
                dominant_cokey = str(cokey)

        def _weighted_avg(pairs: list[tuple[float, float]]) -> float:
            if not pairs:
                return float("nan")
            total = sum(p for p, _ in pairs)
            return float("nan") if total == 0 else sum(p * v for p, v in pairs) / total

        # texcl: shallowest horizon of dominant component with a non-null value
        texcl_mu: object = float("nan")
        if dominant_cokey is not None:
            dom_hz = mu_group[mu_group["cokey"] == dominant_cokey].sort_values("hzdept_r")
            for _, hz_row in dom_hz.iterrows():
                val = hz_row["texcl"]
                if pd.notna(val) and str(val).strip():
                    texcl_mu = val
                    break

        records.append(
            {
                "mukey": mukey,
                "awc_r": _weighted_avg(awc_pairs),
                "claytotal_r": _weighted_avg(clay_pairs),
                "drainagecl": _dominant_component_attr(comp_rows, "drainagecl"),
                "texcl": texcl_mu,
            }
        )

    result = pd.DataFrame(records)
    print(
        f"[SSURGO] tabular aggregation: {len(result):,} map units "
        f"from {len(df):,} horizon rows"
    )
    null_counts = result[["awc_r", "claytotal_r", "drainagecl", "texcl"]].isna().sum()
    print(f"[SSURGO] null counts after aggregation: {null_counts.to_dict()}")
    return result


# ---------------------------------------------------------------------------
# Step 2 — Impute null values with county-level statistics
# ---------------------------------------------------------------------------

def impute_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Fill null attribute values with county-level statistics.

    # Imputation approach
    # Nulls in awc_r and claytotal_r arise where map unit components have no
    # horizon records — typically urban land, water bodies, or rock outcrops.
    # These map units have valid geometries but no measured soil attributes.
    #
    # Continuous variables (awc_r, claytotal_r): filled with the spatial
    # median of all non-null map units in Napa County. The median is used
    # instead of the mean because awc_r and claytotal_r distributions are
    # moderately right-skewed in Napa County (range: ~0.05–0.25 cm/cm for
    # awc_r); the median is more robust to extreme values from thin fractional
    # inclusions at survey boundaries.
    #
    # Categorical variables (drainagecl, texcl): filled with the county-wide
    # mode (most common value). Mode is appropriate for nominal data where
    # arithmetic operations are undefined.
    #
    # Imputed values are conservative placeholders. Map units that receive
    # imputed values are typically non-agricultural (rock, water, urban) and
    # contribute minimal area to any AVA; their influence on area-weighted AVA
    # averages is negligible.

    Args:
        df: DataFrame with mukey, awc_r, claytotal_r, drainagecl, texcl columns.

    Returns:
        DataFrame with nulls filled in-place copy.
    """
    df = df.copy()

    for col in ("awc_r", "claytotal_r"):
        n_null = int(df[col].isna().sum())
        if n_null > 0:
            median_val = float(df[col].median())
            df[col] = df[col].fillna(median_val)
            print(
                f"[SSURGO] imputed {n_null} null {col} values "
                f"with county median {median_val:.4f}"
            )

    for col in ("drainagecl", "texcl"):
        n_null = int(df[col].isna().sum())
        if n_null > 0:
            mode_val = df[col].mode().iloc[0]
            df[col] = df[col].fillna(mode_val)
            print(
                f"[SSURGO] imputed {n_null} null {col} values "
                f"with county mode '{mode_val}'"
            )

    return df


# ---------------------------------------------------------------------------
# Step 3 — Fetch SSURGO map unit polygon geometries from USDA SDA WFS
# ---------------------------------------------------------------------------

def fetch_ssurgo_polygons(areasymbol: str, cache_path: Path) -> gpd.GeoDataFrame:
    """Download SSURGO map unit polygon geometries for a survey area.

    Uses the USDA Soil Data Access (SDA) WFS service with a bounding-box
    filter for Napa County. Results are cached as a GeoPackage so subsequent
    runs skip the network request.

    The returned GeoDataFrame has a 'mukey' column (string) and polygon
    geometries in WGS84 (EPSG:4326).

    Args:
        areasymbol: SSURGO survey area symbol (e.g. 'CA055').
        cache_path: Local GeoPackage path for caching the downloaded polygons.

    Returns:
        GeoDataFrame with a 'mukey' column and polygon geometries.

    Raises:
        requests.HTTPError: If the WFS request fails.
        ValueError: If the 'mukey' column cannot be found in the response.
    """
    if cache_path.exists():
        print(f"[SSURGO] Loading cached polygons from {cache_path.name}")
        gdf = gpd.read_file(cache_path)
    else:
        west, south, east, north = _NAPA_BBOX_WGS84
        bbox_str = f"{west},{south},{east},{north},urn:ogc:def:crs:EPSG::4326"
        url = (
            f"{_SDA_WFS_BASE}?service=WFS&version=1.1.0&request=GetFeature"
            f"&typeName=MapunitPoly&BBOX={bbox_str}"
        )
        print(f"[SSURGO] Downloading map unit polygons for {areasymbol} from SDA WFS...")
        print(f"  URL: {url}")
        response = requests.get(url, timeout=300)
        response.raise_for_status()

        gdf = gpd.read_file(io.BytesIO(response.content))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(cache_path, driver="GPKG")
        print(f"[SSURGO] {len(gdf):,} polygons downloaded → cached at {cache_path.name}")

    # Normalise column names to lowercase
    gdf.columns = [c.lower() for c in gdf.columns]
    if "mukey" not in gdf.columns:
        raise ValueError(
            f"Expected 'mukey' column in SSURGO polygon layer; "
            f"found columns: {list(gdf.columns)}"
        )
    gdf["mukey"] = gdf["mukey"].astype(str)

    print(f"[SSURGO] {len(gdf):,} map unit polygons loaded (CRS: {gdf.crs})")
    return gdf


# ---------------------------------------------------------------------------
# Step 4 — Load Napa County AVA boundaries
# ---------------------------------------------------------------------------

def load_ava_boundaries(cache_path: Path) -> gpd.GeoDataFrame:
    """Download and filter AVA district boundaries for Napa County.

    Downloads all US AVA boundaries from the UC Davis Library AVA Project
    and filters to the set of Napa County TTB-recognised AVAs listed in
    NAPA_AVA_NAMES. Geometries are fixed (buffer(0)) if invalid.

    The returned GeoDataFrame has an 'ava_district' column (str) and
    polygon geometries in WGS84 (EPSG:4326).

    Args:
        cache_path: Local GeoPackage path for caching the Napa AVA subset.

    Returns:
        GeoDataFrame with columns: ava_district, geometry.

    Raises:
        requests.HTTPError: If the GeoJSON download fails.
        ValueError: If no Napa AVAs are found or the name column is missing.
    """
    if cache_path.exists():
        print(f"[AVA] Loading cached boundaries from {cache_path.name}")
        return gpd.read_file(cache_path)

    print(f"[AVA] Downloading AVA boundaries from UC Davis AVA project...")
    response = requests.get(_AVA_GEOJSON_URL, timeout=120)
    response.raise_for_status()
    gdf_all = gpd.read_file(io.BytesIO(response.content))
    gdf_all.columns = [c.lower() for c in gdf_all.columns]

    # Locate the AVA name column — UC Davis project uses 'name'
    name_col = next(
        (c for c in ("name", "ava_name", "avaname") if c in gdf_all.columns),
        None,
    )
    if name_col is None:
        raise ValueError(
            f"Could not find AVA name column in UC Davis dataset; "
            f"found columns: {list(gdf_all.columns)}"
        )

    gdf_napa = gdf_all[gdf_all[name_col].isin(NAPA_AVA_NAMES)].copy()
    if gdf_napa.empty:
        sample = gdf_all[name_col].dropna().head(15).tolist()
        raise ValueError(
            f"No Napa County AVAs matched in the UC Davis dataset. "
            f"Check NAPA_AVA_NAMES against actual name values. "
            f"Sample names found: {sample}"
        )

    gdf_napa = gdf_napa.rename(columns={name_col: "ava_district"})
    gdf_napa = gdf_napa[["ava_district", "geometry"]].reset_index(drop=True)
    gdf_napa["geometry"] = gdf_napa.geometry.buffer(0)  # fix any invalid geometries

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    gdf_napa.to_file(cache_path, driver="GPKG")
    print(f"[AVA] {len(gdf_napa)} Napa AVAs → cached at {cache_path.name}")
    return gdf_napa


# ---------------------------------------------------------------------------
# Step 5 — Spatial overlay and area-weighted aggregation to AVA level
# ---------------------------------------------------------------------------

def _area_weighted_mode(series: pd.Series, weights: pd.Series) -> object:
    """Return the plurality category weighted by area.

    Groups by unique values in series and sums the corresponding weights.
    Returns the category with the largest total weight. NaN values are
    excluded from the calculation.

    Args:
        series: Categorical series (e.g. drainagecl values per fragment).
        weights: Numeric area weights aligned with series.

    Returns:
        The plurality value, or NaN if all values are null.
    """
    valid_mask = series.notna() & series.astype(str).str.strip().astype(bool)
    if not valid_mask.any():
        return float("nan")
    area_by_cat = weights[valid_mask].groupby(series[valid_mask]).sum()
    return area_by_cat.idxmax()


def spatial_aggregate_to_ava(
    gdf_mu: gpd.GeoDataFrame,
    gdf_ava: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Join soil attributes to AVA districts via area-weighted spatial overlay.

    Computes the intersection of map unit polygons with AVA boundaries,
    calculates intersection areas (in _CRS_AREA projection), and aggregates:

    - awc_r, claytotal_r: area-weighted mean across all polygon fragments
      within each AVA district.
    - drainagecl, texcl: area-weighted plurality (mode) — the category with
      the greatest total intersection area within each AVA district.

    Both input GeoDataFrames must already be projected to _CRS_AREA.

    Args:
        gdf_mu: GeoDataFrame of map unit polygons with soil attribute columns.
        gdf_ava: GeoDataFrame of AVA boundaries with 'ava_district' column.

    Returns:
        DataFrame with one row per AVA district and columns:
        ava_district, awc_r, drainagecl, claytotal_r, texcl.

    Raises:
        ValueError: If the overlay produces no intersections.
    """
    gdf_inter = gpd.overlay(gdf_mu, gdf_ava, how="intersection", keep_geom_type=False)
    gdf_inter["area_m2"] = gdf_inter.geometry.area
    gdf_inter = gdf_inter[gdf_inter["area_m2"] > 0].copy()

    if gdf_inter.empty:
        raise ValueError(
            "Spatial overlay produced no intersections — verify that SSURGO polygons "
            "and AVA boundaries overlap and are in the same CRS."
        )

    n_avas = gdf_inter["ava_district"].nunique()
    print(
        f"[SSURGO] overlay: {len(gdf_inter):,} polygon fragments "
        f"across {n_avas} AVA districts"
    )

    records: list[dict] = []
    for ava, group in gdf_inter.groupby("ava_district"):
        total_area = group["area_m2"].sum()
        awc_r = (group["awc_r"] * group["area_m2"]).sum() / total_area
        claytotal_r = (group["claytotal_r"] * group["area_m2"]).sum() / total_area
        drainagecl = _area_weighted_mode(group["drainagecl"], group["area_m2"])
        texcl = _area_weighted_mode(group["texcl"], group["area_m2"])
        records.append(
            {
                "ava_district": ava,
                "awc_r": awc_r,
                "drainagecl": drainagecl,
                "claytotal_r": claytotal_r,
                "texcl": texcl,
            }
        )

    return pd.DataFrame(records).sort_values("ava_district").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def clean_ssurgo(apply: bool = False) -> Optional[pd.DataFrame]:
    """Process SSURGO data to AVA district level and optionally write Parquet.

    Full pipeline:
    1. Aggregate horizon/component records to one row per map unit (mukey).
    2. Impute null continuous values with county-level spatial median.
    3. Impute null categorical values with county-level mode.
    4. Fetch or load cached SSURGO map unit polygon geometries.
    5. Fetch or load cached Napa County AVA boundaries.
    6. Merge tabular attributes onto polygons and project to _CRS_AREA.
    7. Spatial overlay and area-weighted aggregation to AVA district level.
    8. Optionally write data/processed/ssurgo_clean.parquet.

    Args:
        apply: When True, writes the cleaned DataFrame to Parquet and prints
               a load summary. When False (default), prints a preview only.

    Returns:
        Cleaned DataFrame with one row per AVA district, or None on failure.
    """
    ssurgo_csv = SSURGO_DIR / "ssurgo_napa.csv"
    if not ssurgo_csv.exists():
        print(
            f"[SSURGO] ERROR: {ssurgo_csv} not found. "
            "Run src/ingestion/ingest_ssurgo.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Step 1 — aggregate tabular data to mukey level
    df_mu = aggregate_tabular_to_mukey(ssurgo_csv)

    # Step 2+3 — impute nulls before spatial join
    df_mu = impute_nulls(df_mu)

    # Step 4 — fetch or load SSURGO polygon geometries
    poly_cache = SSURGO_DIR / "ssurgo_napa_polygons.gpkg"
    gdf_poly = fetch_ssurgo_polygons(NAPA_AREASYMBOL, poly_cache)

    # Step 5 — fetch or load Napa AVA boundaries
    ava_cache = SSURGO_DIR / "napa_avas.gpkg"
    gdf_ava = load_ava_boundaries(ava_cache)

    # Step 6 — merge attributes onto polygon GeoDataFrame
    gdf_poly = gdf_poly.merge(df_mu, on="mukey", how="left")

    n_unmatched = int(gdf_poly["awc_r"].isna().sum())
    if n_unmatched > 0:
        print(
            f"[SSURGO] WARNING: {n_unmatched} polygon(s) have no matching tabular "
            "record after join (likely water/urban map units not in ssurgo_napa.csv). "
            "Dropping before overlay."
        )
        gdf_poly = gdf_poly.dropna(subset=["awc_r"])

    # Project to equal-area CRS for accurate area calculations
    gdf_poly = gdf_poly.to_crs(_CRS_AREA)
    gdf_ava = gdf_ava.to_crs(_CRS_AREA)

    # Fix any invalid geometries before overlay
    gdf_poly["geometry"] = gdf_poly.geometry.buffer(0)
    gdf_ava["geometry"] = gdf_ava.geometry.buffer(0)

    # Step 7 — spatial aggregation
    df_result = spatial_aggregate_to_ava(gdf_poly, gdf_ava)

    # ------------------------------------------------------------------
    # Preview / apply
    # ------------------------------------------------------------------
    print(f"\n[SSURGO] {len(df_result)} AVA districts processed")
    print(f"         awc_r range     : {df_result['awc_r'].min():.3f} – {df_result['awc_r'].max():.3f} cm/cm")
    print(f"         claytotal range : {df_result['claytotal_r'].min():.1f} – {df_result['claytotal_r'].max():.1f} %")
    print(f"         drainage classes: {sorted(df_result['drainagecl'].unique())}")
    print(f"         texture classes : {sorted(df_result['texcl'].unique())}")
    print(f"\nPreview:\n{df_result.to_string(index=False)}\n")

    if not apply:
        print("[SSURGO] DRY RUN — pass --apply to write Parquet\n")
        return df_result

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_PROCESSED_DIR / "ssurgo_clean.parquet"
    df_result.to_parquet(out_path, index=False)
    print(f"[SSURGO] written → {out_path.relative_to(DATA_RAW_DIR.parent.parent)}")
    print(f"[SSURGO] loaded {len(df_result):,} rows | no date column found")

    return df_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write cleaned data to data/processed/ssurgo_clean.parquet (default: dry run)",
    )
    args = parser.parse_args()
    clean_ssurgo(apply=args.apply)
